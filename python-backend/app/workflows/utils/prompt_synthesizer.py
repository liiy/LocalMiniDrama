"""全剧资产四维提示词解耦与视觉/声学提示词合成器 (PromptSynthesizer)。

【提示词四维解耦架构】：
1. identity_prompt: 生物人脸与本体特征基准锚点（仅五官、发型、骨相、生物DNA，剥离服饰、姿态与情绪）。
2. delta_prompt: 视角、机位、定妆、表情、光影增量修饰词。
3. composed_visual_prompt / image_prompt: 物理执行的完整视听正向提示词 (identity + delta + style)。
4. negative_prompt: 分资产大类的工业级通用与专属排斥词。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping, NamedTuple

from app.workflows.utils.asset_protocol import AssetProtocolHelper

logger = logging.getLogger(__name__)


class SynthesizedPrompt(tuple):
    """合成提示词双元组，兼容 (delta, visual) 2-tuple 解构与四维属性访问。"""
    delta_prompt: str
    visual_prompt: str
    identity_prompt: str
    negative_prompt: str

    def __new__(
        cls,
        delta_prompt: str,
        visual_prompt: str,
        identity_prompt: str = "",
        negative_prompt: str = "",
    ) -> SynthesizedPrompt:
        instance = super().__new__(cls, (delta_prompt, visual_prompt))
        instance.delta_prompt = delta_prompt
        instance.visual_prompt = visual_prompt
        instance.identity_prompt = identity_prompt
        instance.negative_prompt = negative_prompt
        return instance


class PhysicalEntityState(NamedTuple):
    """物理实体连续性状态元组。"""
    entity_id: str               # 资产ID，如 PROP_PORTRAIT_FRAME 或 PROP_ENVELOPE
    status: str                  # 状态标签，如 "pristine", "cracked", "shattered", "opened", "moved"
    wear_delta: str              # 破损/位移增量描述，如 "spiderweb hairline crack on upper right glass"
    spatial_anchor: str          # 空间锚点，如 "altar_table_center"
    visual_evidence_token: str   # 注入后续镜头的提示词补丁，如 "maintaining visible cracks on frame glass"


class ContinuityStateManager:
    """分镜物理连续性状态机（跨镜头物理资产状态跟踪与提示词增量补丁注入器）。"""

    def __init__(self) -> None:
        self.active_props_states: dict[str, PhysicalEntityState] = {}
        self.active_characters_costumes: dict[str, str] = {}
        self.environment_lighting_state: str = ""
        self.appearance_history: dict[str, list[int]] = {}

    def record_shot_appearance(self, shot_idx: int, asset_ids: list[str]) -> None:
        """记录资产在特定镜头的登场历史。"""
        for aid in asset_ids or []:
            aid_up = str(aid).upper()
            if aid_up not in self.appearance_history:
                self.appearance_history[aid_up] = []
            if shot_idx not in self.appearance_history[aid_up]:
                self.appearance_history[aid_up].append(shot_idx)

    def update_entity_state(
        self,
        entity_id: str,
        state_dict: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """更新指定实体的连续性物理状态（角色衣着、道具破坏等）。
        
        支持字典或键值对多重入参风格。
        """
        e_id = str(entity_id).upper()
        merged = dict(state_dict or {})
        merged.update(kwargs)

        if "costume" in merged or merged.get("entity_type") == "character":
            c_val = merged.get("costume") or merged.get("state_desc") or "custom_costume"
            self.active_characters_costumes[e_id] = c_val

        if any(k in merged for k in ("damage", "wear", "location_in_scene", "damage_level", "state_desc")) or merged.get("entity_type") == "prop":
            damage = merged.get("damage") or merged.get("damage_level") or merged.get("state_desc") or merged.get("wear") or "damaged"
            loc = merged.get("location_in_scene") or "current_scene"
            self.active_props_states[e_id] = PhysicalEntityState(
                entity_id=e_id,
                status=damage,
                wear_delta=f"{damage} at {loc}",
                spatial_anchor=loc,
                visual_evidence_token=f"maintaining {damage} physical state at {loc}",
            )

    def get_prompt_injection_for_shot(self, shot_idx: int, asset_ids: list[str]) -> dict[str, Any]:
        """获取当前镜头涉及资产的连续性快照与提示词补丁。"""
        snap = self.export_snapshot(shot_number=shot_idx)
        patches: list[str] = []
        for aid in asset_ids or []:
            aid_up = str(aid).upper()
            if aid_up in self.active_props_states:
                p_state = self.active_props_states[aid_up]
                if p_state.visual_evidence_token:
                    patches.append(p_state.visual_evidence_token)
        snap["prompt_patch"] = ", ".join(patches)
        return snap

    def export_snapshot(self, shot_number: int | str = 1) -> dict[str, Any]:
        """导出当前连续性快照。"""
        entities: dict[str, Any] = {}
        for c_id, costume in self.active_characters_costumes.items():
            entities[c_id] = {"costume": costume}
        for p_id, p_state in self.active_props_states.items():
            entities[p_id] = {
                "damage": p_state.status,
                "location_in_scene": p_state.spatial_anchor,
                "wear_delta": p_state.wear_delta,
            }
        return {
            "shot_number": shot_number,
            "entities": entities,
            "props_states": {k: v._asdict() for k, v in self.active_props_states.items()},
            "characters_costumes": dict(self.active_characters_costumes),
            "environment_lighting": self.environment_lighting_state,
        }

    def step_and_snapshot(self, shot_dict: dict[str, Any]) -> dict[str, Any]:
        """根据当前镜头内容更新物理状态，并生成可序列化的当前分镜连续性快照。"""
        shot_id = shot_dict.get("shot_id")
        combined_text = " ".join([
            str(shot_dict.get("action") or ""),
            str(shot_dict.get("image_prompt") or ""),
            str(shot_dict.get("video_prompt") or ""),
            str(shot_dict.get("dynamic_cue") or ""),
            str((shot_dict.get("audio") or {}).get("foley") or ""),
        ])

        # 扫描物证道具物理变化（破裂、碎裂、撕开、抽出、倾倒等）
        prop_ids = shot_dict.get("prop_asset_ids") or []
        for pid in prop_ids:
            pid_str = str(pid).upper()
            if any(k in combined_text for k in ("碎裂", "微裂", "裂纹", "破损", "crack", "shatter", "broken")):
                self.active_props_states[pid_str] = PhysicalEntityState(
                    entity_id=pid_str,
                    status="cracked",
                    wear_delta="visible spiderweb hairline cracks on surface, fragile glass stress",
                    spatial_anchor="current_focus",
                    visual_evidence_token="maintaining preexisting visible cracks on surface, realistic physical wear",
                )
                logger.debug("【物理连续性状态机】shot_id=%s 记录道具破损状态: %s -> cracked", shot_id, pid_str)
            elif any(k in combined_text for k in ("撕开", "抽出", "展开", "拆开", "open", "torn", "extracted")):
                self.active_props_states[pid_str] = PhysicalEntityState(
                    entity_id=pid_str,
                    status="opened",
                    wear_delta="unfolded and exposed edges, paper creases",
                    spatial_anchor="in_hand_or_surface",
                    visual_evidence_token="maintaining opened and unfolded physical form, visible creases",
                )
                logger.debug("【物理连续性状态机】shot_id=%s 记录道具开启状态: %s -> opened", shot_id, pid_str)

        # 扫描光影环境微气候（如烛光摇曳、阴风、冷暖色调切换）
        if any(k in combined_text for k in ("阴风", "闪烁", "忽明忽暗", "烛火摇曳", "flickering")):
            self.environment_lighting_state = "flickering candlelight under chilly draft, high contrast shadows"
        elif any(k in combined_text for k in ("雷电", "闪电", "爆闪", "lightning")):
            self.environment_lighting_state = "dramatic periodic lightning flash casting cold white rim highlights"

        snapshot = {
            "shot_id": shot_id,
            "props_states": {k: v._asdict() for k, v in self.active_props_states.items()},
            "characters_costumes": dict(self.active_characters_costumes),
            "environment_lighting": self.environment_lighting_state,
        }
        return snapshot

    def inject_continuity_into_prompt(self, shot_dict: dict[str, Any], prompt_text: str) -> str:
        """为当前镜头注入前置继承的物理连续性提示词补丁。"""
        if not prompt_text:
            return prompt_text
        text_out = prompt_text
        prop_ids = shot_dict.get("prop_asset_ids") or []
        for pid in prop_ids:
            pid_str = str(pid).upper()
            if pid_str in self.active_props_states:
                state = self.active_props_states[pid_str]
                if state.visual_evidence_token and state.visual_evidence_token.lower() not in text_out.lower():
                    text_out = f"{text_out.rstrip(' ,')}, {state.visual_evidence_token}"
        return text_out


GLOBAL_NEGATIVE_PROMPTS: dict[str, str] = {
    "GENERAL_NEGATIVE": (
        "deformed, distorted, disfigured, bad anatomy, poorly drawn face, poorly drawn hands, "
        "missing limb, floating limbs, disconnected limbs, extra arms, extra legs, mutation, mutated, "
        "blurry, bad art, low quality, artifacts, watermark, signature, username, text, worst quality, "
        "lowres, jpeg artifacts, duplicate, cropped, extra fingers, mutated hands"
    ),
    "CHARACTER_NEGATIVE": (
        "cropped feet, cut off feet, out of frame legs, feet out of frame, cut off shoes, "
        "head cropped, partial body, cropped limbs, cut off head, missing shoes, "
        "complex background, detailed background, street, outdoor, room, furniture, nature, trees, cars, environmental clutter, "
        "caucasian, western face, anime render, 3d render, doll-like, plastic skin, airbrushed, cartoon, "
        "oversaturated, deformed face, asymmetrical eyes, missing teeth, extra teeth, "
        "unrealistic hair, extra limbs, low polygon, smooth porcelain skin, distorted iris, cross-eyed, deformed mouth, extra digits, "
        "turnaround sheet, character sheet, multiple views, multiple angles, split screen, 4-grid, 3-view, "
        "collage, diptych, triptych, reference sheet, multiple people, two persons, crowd, group of people"
    ),
    "SCENE_NEGATIVE": (
        "modern elements in ancient scene, steel and concrete in period setting, electric cables, "
        "neon lights, cars, indoor clutter, floating furniture, warped perspective, "
        "crooked architecture, unnatural lighting, artifacts, CGI look, blurry background, low-res texture, "
        "watermark, signature, text, oversaturated lighting, distorted walls"
    ),
    "PROP_NEGATIVE": (
        "human, person, man, woman, face, portrait, eyes, mouth, nose, head, hair, skin, hands, fingers, body, human figure, mannequin, "
        "floating object, deformed object, unrealistic proportions, floating parts, inconsistent texture, melted look, "
        "broken mesh, watermark, signature, bad lighting, low resolution, blurry surface"
    ),
    "VOICE_NEGATIVE": (
        "robotic, tinny, electric noise, metallic voice, harsh sibilance, distorted audio, background static, "
        "clipping, breath pops, unnatural pitch shift, mumbled pronunciation"
    ),
}


class PromptSynthesizer:
    """资产提示词四维解耦与合成服务类。"""

    @classmethod
    def get_negative_prompt(cls, category: str) -> str:
        """根据资产大类返回工业级负向提示词 (Negative Prompt)。"""
        cat = category.strip().upper() if category else ""
        gen_neg = GLOBAL_NEGATIVE_PROMPTS["GENERAL_NEGATIVE"]
        if cat in ("CHAR", "CHARACTER"):
            return f"{GLOBAL_NEGATIVE_PROMPTS['CHARACTER_NEGATIVE']}, {gen_neg}"
        elif cat in ("ENV", "SCENE", "ENVIRONMENT"):
            return f"{GLOBAL_NEGATIVE_PROMPTS['SCENE_NEGATIVE']}, {gen_neg}"
        elif cat in ("PROP",):
            return f"{GLOBAL_NEGATIVE_PROMPTS['PROP_NEGATIVE']}, {gen_neg}"
        elif cat in ("VOICE", "AUDIO"):
            return GLOBAL_NEGATIVE_PROMPTS["VOICE_NEGATIVE"]
        return gen_neg

    @classmethod
    def get_category_negative_prompt(cls, category: str) -> str:
        """别名：根据资产大类返回负向提示词。"""
        return cls.get_negative_prompt(category)

    @classmethod
    def extract_character_identity_prompt(cls, character_data: Any) -> str:
        """别名：从角色档案中提取 0 号人脸基准特征。"""
        return cls.extract_identity_face_anchor(character_data)

    @classmethod
    def extract_identity_face_anchor(cls, character_data: Any) -> str:
        """从角色档案中提取 0 号人脸与生物基因基准特征 (Face Identity Anchor)。
        
        【设计约束】：严格提取五官、脸型、骨相、肤质、发型与年龄生物特征，
        剥离服饰、穿戴饰品、动作姿态与多变情绪，确保全剧无论换装还是转角均具备统一的面孔基底。
        """
        if hasattr(character_data, "model_dump"):
            data = character_data.model_dump()
        elif hasattr(character_data, "to_dict"):
            data = character_data.to_dict()
        elif isinstance(character_data, Mapping):
            data = dict(character_data)
        else:
            data = {}

        bio = data.get("biological_dna") or {}
        if not isinstance(bio, dict):
            bio = {}

        bone = bio.get("bone_structure") or "high cheekbones, structured jawline"
        skin = bio.get("skin_micro_texture") or "realistic raw skin micro-texture, visible pores and natural fine lines"
        scars = bio.get("blemishes_and_scars") or ""
        eyes_lips = bio.get("eye_lip_anatomy") or "clear defined eyes, natural lip contour"
        hair = bio.get("hair_texture") or "natural textured black hair"

        appearance = str(data.get("appearance") or "")
        # 清洗掉可能带入的服饰与姿态词汇
        appearance_clean = re.sub(
            r"(穿着|身穿|着装|佩戴|上装|下装|大衣|夹克|西装|裙|鞋|裤|拿|手握)[^，。,；]*[，。,；]?",
            "",
            appearance,
        ).strip()

        # 组合纯净的人脸生物特征锚点
        parts: list[str] = [
            "masterpiece 8k portrait photography",
            "East Asian Chinese biological features",
            f"facial bone structure: {bone}",
            f"skin texture: {skin}",
            f"eyes and lips: {eyes_lips}",
            f"hair style: {hair}",
        ]
        if scars:
            parts.append(f"distinguishing marks: {scars}")
        if appearance_clean:
            parts.append(f"physique overview: {appearance_clean}")

        return ", ".join(parts)

    @classmethod
    def extract_prop_physical_anchor(cls, prop_data: Any) -> str:
        """从道具对象或描述中提取纯净物性基准特征 (Prop Physical Anchor)。

        【设计约束与生物隔离铁律】：
        严格提取材质(material)、工艺纹理(craft)、做旧包浆(patina)、几何尺寸与摆放承载面(resting_surface)，
        严禁提取人脸、五官、骨相、肤质、发型或任何生物人像特征，彻底杜绝人脸肖像污染道具提示词。
        """
        if hasattr(prop_data, "model_dump"):
            data = prop_data.model_dump()
        elif hasattr(prop_data, "to_dict"):
            data = prop_data.to_dict()
        elif isinstance(prop_data, Mapping):
            data = dict(prop_data)
        elif isinstance(prop_data, str):
            data = {"name": prop_data, "visual_prompt": prop_data}
        else:
            data = {}

        name = str(data.get("name") or data.get("prop_name") or "").strip()
        material = str(data.get("material_specs") or data.get("material") or data.get("material_details") or "").strip()
        craft = str(data.get("craft_texture") or data.get("craft") or "").strip()
        surface = str(data.get("resting_surface") or data.get("placement_surface") or "").strip()
        patina = str(data.get("patina_degree") or data.get("wear_and_tear") or "").strip()
        vp = str(data.get("visual_prompt") or data.get("prompt") or "").strip()

        # 清洗掉可能带入的生物/面部/肖像特征词汇（防污染过滤，采用分句级过滤加词组清洗）
        bio_purge_pattern = (
            r"(East Asian|Chinese|facial|bone structure|skin micro-texture|visible pores|"
            r"fine lines|eyes and lips|hair style|cheekbones|jawline|portrait|portrait photography|"
            r"生物特征|五官|脸型|骨相|肤质|毛孔|双眼|嘴唇|发型|肖像|剑眉|星目|冷酷|脸庞|刀疤|眼神|眉毛|鼻梁|胡须|体态|神情|身形)"
        )
        if vp:
            # 1. 分句过滤：按中英文句号、分号分句，凡包含人物肖像生物词汇的整句彻底剔除
            sentences = re.split(r"[。；;\n]", vp)
            clean_sentences = []
            for sent in sentences:
                sent_str = sent.strip()
                if not sent_str:
                    continue
                if re.search(bio_purge_pattern, sent_str, flags=re.IGNORECASE):
                    continue
                clean_sentences.append(sent_str)
            vp_clean = "，".join(clean_sentences)
            # 2. 细粒度清洗遗留词
            vp_clean = re.sub(bio_purge_pattern, "", vp_clean, flags=re.IGNORECASE)
            vp_clean = re.sub(r"\s*[,，]\s*[,，]\s*", "，", vp_clean).strip(" ,，")
        else:
            vp_clean = ""

        parts: list[str] = [
            "masterpiece 8k studio product photography",
            "isolated hero prop",
            f"physical object: {name or 'narrative prop'}",
        ]
        if material:
            parts.append(f"material specifications: {material}")
        if craft:
            parts.append(f"craft and micro-texture: {craft}")
        if surface and surface not in ("无", "none", "null"):
            parts.append(f"grounded resting surface: {surface}")
        if patina and patina not in ("无", "none", "null"):
            parts.append(f"aging and patina: {patina}")
        if vp_clean and vp_clean != name:
            parts.append(f"visual details: {vp_clean}")

        return ", ".join(parts)

    @classmethod
    def synthesize_character_view_prompt(
        cls,
        character_or_identity: Any,
        view_type: str = "BASE_PORTRAIT",
        costume_prompt: str = "",
        expression_prompt: str = "",
        lighting_prompt: str = "",
        visual_style: str = "cinematic photorealistic 8k, gritty film grain, realistic dramatic lighting",
        **kwargs: Any,
    ) -> tuple[str, str]:
        """合成角色分视图增量提示词 (delta_prompt) 与最终执行提示词 (composed_visual_prompt)。
        
        :param character_or_identity: 提取的面部特征字符串，或角色字典/模型对象
        :param view_type: BASE_PORTRAIT / BASE_COSTUME / 4V_FRONT / 4V_SIDE / 4V_BACK / 4V_THREE_QUARTER / EXP / STATUS / MACRO
        :param costume_prompt: 阶段服装穿戴描述 (top_wear, bottom_wear, footwear)
        :param expression_prompt: 微表情或情绪描述
        :param lighting_prompt: 视听光影设定描述
        :param visual_style: 全局艺术视觉风格
        :return: (delta_prompt, composed_visual_prompt)
        """
        if isinstance(character_or_identity, str):
            identity_prompt = character_or_identity
        else:
            identity_prompt = cls.extract_identity_face_anchor(character_or_identity)

        v_style = kwargs.get("style_modifiers") or visual_style
        if not costume_prompt and not isinstance(character_or_identity, str):
            if isinstance(character_or_identity, dict):
                costume_prompt = str(character_or_identity.get("costume_description") or character_or_identity.get("costume") or "")
            else:
                costume_prompt = str(getattr(character_or_identity, "costume_description", "") or getattr(character_or_identity, "costume", ""))

        vt = view_type.strip().upper()
        delta_parts: list[str] = []

        if vt in ("BASE_PORTRAIT", "PORTRAIT", "MAIN_PORTRAIT", "T1_BASE"):
            # 【Tier 1 纯面部物理隔离约束】：
            # 严格剥离任何服饰、外套、首饰及环境要素，仅保留头部、颈部与裸肩锁骨，在中性暗灰摄影底板下生成纯粹的 FaceID 基准
            delta_parts.append(
                "single person, close-up frontal headshot portrait, neutral frontal headshot portrait, 85mm portrait lens, eye-level framing, "
                "neutral resting facial expression, shallow depth of field, razor sharp focus on eyes and facial skin micro-textures, "
                "bare shoulders, visible collarbone and neck, completely isolated subject, clean solid neutral dark gray studio photography backdrop, "
                "completely blank neutral dark gray studio photography backdrop, pure solid dark gray background, "
                "zero environmental elements, zero clothing details, no jacket, no shirt, no background clutter"
            )
        elif vt in ("BASE_COSTUME", "COSTUME", "FULL_BODY", "FULLBODY"):
            costume_desc = costume_prompt or "tailored character outfit, realistic textured fabric folds"
            delta_parts.append(
                f"single person, wide angle full-length shot, complete body from top of head to soles of shoes, uncropped standing full body silhouette, eye-level framing, clear negative space above head and below feet, standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, both feet and shoes firmly planted on the ground with soles visible, wearing {costume_desc}, natural relaxed posture, neutral facial expression, realistic fabric drape and creases, clean solid neutral gray studio backplate, isolated full body figure, no background clutter"
            )
        elif vt in ("4V_FRONT", "FRONT", "FRONT_VIEW", "T1_4V_FRONT_FULL"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, wide angle full-length front view portrait, complete body from top of head to soles of shoes, uncropped full body standing front view, neutral A-pose, facing camera directly, centered composition, clear negative space above head and below feet, standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, both feet firmly planted on the ground, complete footwear and soles visible, wearing {costume_desc}, clean solid neutral gray studio backdrop, flat even studio reference lighting, ortho camera perspective, symmetry, isolated figure, no background clutter"
            )
        elif vt in ("4V_SIDE", "SIDE", "SIDE_VIEW", "PROFILE", "4V_PROFILE", "T2_4V_PROFILE"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, wide angle full-length exact 90-degree side profile view, complete body from top of head to soles of shoes, uncropped silhouette, neutral A-pose, facing sideways, clear negative space above head and below feet, standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, both feet firmly planted on the ground with footwear visible, wearing {costume_desc}, clean solid neutral gray studio backdrop, flat even studio reference lighting, ortho camera perspective, isolated figure, no background clutter"
            )
        elif vt in ("4V_BACK", "BACK", "BACK_VIEW", "REAR", "T2_4V_BACK"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, wide angle full-length 180-degree rear back view showing back details, complete body from top of head to soles of shoes, uncropped silhouette, neutral A-pose, facing away from camera, clear negative space above head and below feet, standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, both feet firmly planted on the ground with shoes visible, wearing {costume_desc}, clean solid neutral gray studio backdrop, flat even studio reference lighting, ortho camera perspective, isolated figure, no background clutter"
            )
        elif vt in ("4V_THREE_QUARTER", "THREE_QUARTER", "THREE_QUARTER_VIEW", "4V_3Q", "3Q", "T2_4V_3Q"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, wide angle full-length 45-degree three-quarter view, complete body from top of head to soles of shoes, uncropped silhouette, neutral A-pose, turned at three-quarter angle, clear negative space above head and below feet, standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, both feet firmly planted on the ground with footwear visible, wearing {costume_desc}, clean solid neutral gray studio backdrop, flat even studio reference lighting, ortho camera perspective, isolated figure, no background clutter"
            )
        elif vt.startswith("EXP"):
            exp_desc = expression_prompt or "subtle emotional micro-expression"
            delta_parts.append(
                f"single person, tight close-up face shot, 85mm lens, {exp_desc}, authentic human emotional reaction, intense eye gaze, dynamic high-contrast side lighting, cinematic tension"
            )
        elif vt.startswith("STATUS"):
            status_desc = expression_prompt or "battle-worn, exhausted, slight facial abrasion"
            costume_desc = costume_prompt or "weathered ragged clothing"
            delta_parts.append(
                f"single person, waist-up medium shot, {status_desc}, wearing distressed {costume_desc}, visible grime, scuffs, sweat, dramatic moody lighting, visceral cinematic realism"
            )
        elif vt in ("MACRO_FACE", "MACRO_FACIAL", "FACIAL_MACRO"):
            delta_parts.append(
                "extreme close-up macro facial detail shot, tight framing on eyes, nose, lips and biological skin texture, micro-blemishes, 100mm macro portrait lens, ultra-shallow depth of field, razor sharp focus"
            )
        elif vt in ("MACRO_HAND", "MACRO_HANDS", "HANDS_DETAIL"):
            delta_parts.append(
                "extreme close-up macro detail of hands and fingers, authentic skin pores and nails, realistic hand anatomy, 100mm macro lens, ultra-shallow depth of field, sharp focus on hand gesture"
            )
        elif vt.startswith("MACRO"):
            delta_parts.append(
                "extreme macro detail shot, tight framing on physiological feature or hand gesture, tactile skin texture, micro-blemishes, 100mm macro lens, ultra-shallow depth of field"
            )
        else:
            delta_parts.append(f"single person, cinematic shot, {view_type} framing, wearing {costume_prompt or 'standard outfit'}")

        if lighting_prompt:
            delta_parts.append(f"lighting setup: {lighting_prompt}")

        delta_prompt = "; ".join(delta_parts)
        composed = (
            f"cinematic photorealistic 8k, {identity_prompt}, {delta_prompt}, "
            f"visual style: {v_style} --style raw"
        )
        neg = cls.get_negative_prompt("character")
        return SynthesizedPrompt(delta_prompt, composed, identity_prompt=identity_prompt, negative_prompt=neg)

    @classmethod
    def synthesize_scene_view_prompt(
        cls,
        scene_or_prompt: Any,
        view_type: str = "WIDE",
        weathering_prompt: str = "",
        atmosphere_prompt: str = "",
        visual_style: str = "cinematic photorealistic 8k, gritty film grain, realistic dramatic lighting",
        **kwargs: Any,
    ) -> SynthesizedPrompt:
        """合成场景分视图增量提示词与执行提示词。
        
        :param scene_or_prompt: 主空间基础建筑材质文本，或场景字典/模型对象
        :param view_type: WIDE / OTS_BG / STATE / INSERT / KEYFRAME
        :param weathering_prompt: 风化、做旧与气候演化
        :param atmosphere_prompt: 空间氛围与色温
        :param visual_style: 全局艺术视觉风格
        :return: SynthesizedPrompt(delta_prompt, composed_visual_prompt)
        """
        if isinstance(scene_or_prompt, str):
            base_scene_prompt = scene_or_prompt
        elif isinstance(scene_or_prompt, dict):
            base_scene_prompt = str(scene_or_prompt.get("visual_prompt") or scene_or_prompt.get("prompt") or scene_or_prompt.get("location") or "")
        else:
            base_scene_prompt = str(getattr(scene_or_prompt, "visual_prompt", "") or getattr(scene_or_prompt, "location", ""))

        v_style = kwargs.get("style_modifiers") or visual_style
        vt = view_type.strip().upper()
        delta_parts: list[str] = []

        if vt in ("WIDE", "MASTER"):
            delta_parts.append(
                "wide-angle establishing master shot, 24mm anamorphic lens, expansive field of view, grand architectural geometry, deep depth of field, establishing scene geography"
            )
        elif vt in ("OTS_BG", "OTS"):
            delta_parts.append(
                "over-the-shoulder conversation background plate, 50mm lens, shallow depth of field, cinematic bokeh blur on background, soft ambient fill light, dialogue interior framing"
            )
        elif vt.startswith("STATE"):
            weath = weathering_prompt or "weather-worn surfaces, atmospheric aging"
            delta_parts.append(
                f"altered environmental state, {weath}, dynamic weather transition, altered lighting and color temperature, cinematic mood change"
            )
        elif vt in ("INSERT", "CUTAWAY"):
            delta_parts.append(
                "macro insert cutaway shot, tight framing on localized spatial details, intimate still life composition, textured surfaces, shallow focus"
            )
        elif vt in ("KEYFRAME",):
            delta_parts.append(
                "cinematic narrative keyframe, balanced medium-wide composition, storytelling lighting, transition pacing"
            )
        else:
            delta_parts.append(f"scene view {view_type}")

        if atmosphere_prompt:
            delta_parts.append(f"spatial atmosphere: {atmosphere_prompt}")

        delta_prompt = "; ".join(delta_parts)
        base = base_scene_prompt or "photorealistic interior environment"
        composed = (
            f"cinematic photorealistic 8k architectural environment, {base}, {delta_prompt}, "
            f"visual style: {v_style} --style raw"
        )
        neg = cls.get_negative_prompt("environment")
        return SynthesizedPrompt(delta_prompt, composed, identity_prompt=base, negative_prompt=neg)

    @classmethod
    def synthesize_prop_view_prompt(
        cls,
        prop_or_prompt: Any,
        view_type: str = "STATIC",
        state_prompt: str = "",
        visual_style: str = "cinematic photorealistic 8k, gritty film grain, realistic dramatic lighting",
        **kwargs: Any,
    ) -> SynthesizedPrompt:
        """合成道具分视图增量提示词与执行提示词。
        
        :param prop_or_prompt: 核心物证初始造型描述，或道具字典/模型对象
        :param view_type: STATIC / ACTION / DETAIL
        :param state_prompt: 战损、破坏形态或使用痕迹
        :param visual_style: 全局艺术视觉风格
        :return: SynthesizedPrompt(delta_prompt, composed_visual_prompt)
        """
        if isinstance(prop_or_prompt, (dict, Mapping)) or hasattr(prop_or_prompt, "model_dump"):
            base_prop_prompt = cls.extract_prop_physical_anchor(prop_or_prompt)
        elif isinstance(prop_or_prompt, str):
            # 过滤可能误传的人脸肖像词汇，阻断生物特征污染
            bio_purge_pattern = (
                r"(East Asian|Chinese|facial bone|skin micro-texture|visible pores|"
                r"fine lines|eyes and lips|hair style|cheekbones|jawline|portrait photography|"
                r"生物特征|五官|脸型|骨相|肤质|毛孔|双眼|嘴唇|发型|肖像)"
            )
            clean_str = re.sub(bio_purge_pattern, "", prop_or_prompt, flags=re.IGNORECASE)
            clean_str = re.sub(r"\s*,\s*,\s*", ", ", clean_str).strip(" ,")
            base_prop_prompt = clean_str or prop_or_prompt
        else:
            base_prop_prompt = str(getattr(prop_or_prompt, "visual_prompt", "") or getattr(prop_or_prompt, "name", ""))

        v_style = kwargs.get("style_modifiers") or visual_style
        vt = view_type.strip().upper()
        delta_parts: list[str] = []

        if vt in ("STATIC", "STILL"):
            delta_parts.append(
                "isolated hero prop studio shot, resting on a textured wooden table or stone surface, 100mm macro lens, pristine condition, centered composition, soft three-point product lighting, neutral dark gray backdrop, sharp focus on surface material, grounded physical contact"
            )
        elif vt in ("ACTION", "INTERACTION"):
            s_desc = state_prompt or "functional interaction state"
            delta_parts.append(
                f"dynamic hand-held prop in narrative action, {s_desc}, active character hand interaction, motion context, resting against tactile surface or held firmly in hand, shallow depth of field, dramatic cinematic side light"
            )
        elif vt in ("DETAIL", "MACRO"):
            s_desc = f", {state_prompt}" if state_prompt else ""
            delta_parts.append(
                f"extreme macro texture shot, resting firmly on physical substrate, tactile material fissures, mechanical engravings, microscopic wear and tear, micro depth of field{s_desc}"
            )
        else:
            delta_parts.append(f"prop view {view_type}, state: {state_prompt or 'default'}")

        delta_prompt = "; ".join(delta_parts)
        base = base_prop_prompt or "photorealistic physical object"
        composed = (
            f"cinematic photorealistic 8k hero prop, {base}, {delta_prompt}, "
            f"visual style: {v_style} --style raw"
        )
        neg = cls.get_negative_prompt("prop")
        return SynthesizedPrompt(delta_prompt, composed, identity_prompt=base, negative_prompt=neg)

    @classmethod
    def enrich_narrative_prompt(
        cls,
        base_prompt: str,
        category: str,
        narrative_context: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """为大模型输出的初始提示词执行剧情感官物理细节增强与去空洞化治理。
        
        :param base_prompt: 大模型生成的原始提示词
        :param category: character / scene / prop / environment
        :param narrative_context: 当集剧情上下文字典（包含 weather, lighting, battle_damage, emotion, camera_spec, interaction_surface 等）
        :param visual_style: 全局视觉风格
        :return: 剧情感官深度融合后的高精度生图提示词
        """
        prompt = str(base_prompt or "").strip()
        ctx = narrative_context or {}
        cat = category.strip().lower()

        # 1. 彻底清洗空洞占位符
        cleaned_style = visual_style.strip() if visual_style else "cinematic photorealistic 8k, gritty film grain, realistic dramatic lighting"
        prompt = re.sub(r"visual style:\s*\[?visual_style\]?", f"visual style: {cleaned_style}", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\[visual_style\]", cleaned_style, prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\[placeholder\]", "", prompt, flags=re.IGNORECASE)

        # 2. 按大类提取剧情物理感官增强短语
        enrichment_tags: list[str] = []

        if cat in ("character", "char"):
            emotion = str(ctx.get("emotion") or ctx.get("expression") or "").strip()
            damage = str(ctx.get("battle_damage") or ctx.get("trauma") or ctx.get("scars") or "").strip()
            lens = str(ctx.get("camera_lens") or "85mm portrait lens, shallow depth of field, sharp focus on facial bone structure").strip()
            grounding = "standing firmly on ground, realistic soft contact cast shadows under shoes, completely uncropped silhouette"
            # 严格防线：若提示词明确为近景面部特写 (headshot / close-up / portrait)，坚决不追加全身站姿与鞋底接触阴影
            is_headshot = any(k in prompt.lower() for k in ("headshot", "close-up", "face", "bare shoulders", "collarbone"))

            if emotion and emotion.lower() not in prompt.lower():
                enrichment_tags.append(f"narrative micro-expression: {emotion}")
            if damage and damage.lower() not in prompt.lower():
                enrichment_tags.append(f"visceral battle damage: {damage}, realistic skin abrasion and subtle bloodstain texture")
            if "lens" not in prompt.lower() and not is_headshot:
                enrichment_tags.append(lens)
            if not is_headshot and "shadow" not in prompt.lower() and ("standing" in prompt.lower() or "full" in prompt.lower()):
                enrichment_tags.append(grounding)

        elif cat in ("scene", "env", "environment"):
            weather = str(ctx.get("weather") or ctx.get("climate") or "").strip()
            lighting = str(ctx.get("lighting") or ctx.get("time_lighting") or "").strip()
            traces = str(ctx.get("narrative_traces") or ctx.get("trace") or ctx.get("debris") or "").strip()
            lens = str(ctx.get("camera_lens") or "35mm cinematic anamorphic lens, grand environmental perspective, rich atmospheric depth").strip()

            if traces and traces.lower() not in prompt.lower():
                enrichment_tags.append(f"narrative scene trace: {traces}")
            if weather and weather.lower() not in prompt.lower():
                enrichment_tags.append(f"atmospheric weather condition: {weather}")
            if lighting and lighting.lower() not in prompt.lower():
                enrichment_tags.append(f"dramatic dynamic lighting: {lighting}")
            if "lens" not in prompt.lower() and "wide" in prompt.lower():
                enrichment_tags.append(lens)

        elif cat in ("prop", "item"):
            surface = str(ctx.get("placement_surface") or ctx.get("surface") or "resting firmly on textured dark weathered table surface").strip()
            wear = str(ctx.get("wear_and_tear") or ctx.get("damage") or "tactile surface micro-scratches, realistic edge wear, mechanical material friction").strip()
            lens = str(ctx.get("camera_lens") or "100mm macro lens, ultra-shallow depth of field, razor sharp focus on object texture").strip()

            if "resting" not in prompt.lower() and "hand" not in prompt.lower():
                enrichment_tags.append(f"grounded physics: {surface}")
            if "scratch" not in prompt.lower() and "wear" not in prompt.lower():
                enrichment_tags.append(f"authentic physical texture: {wear}")
            if "macro" not in prompt.lower() and "lens" not in prompt.lower():
                enrichment_tags.append(lens)

        # 3. 将增强短语合流编排入提示词
        if enrichment_tags:
            enrichment_str = ", ".join(enrichment_tags)
            if "--style raw" in prompt:
                prefix, suffix = prompt.split("--style raw", 1)
                prompt = f"{prefix.rstrip(' ,')}, {enrichment_str} --style raw{suffix}"
            else:
                prompt = f"{prompt.rstrip(' ,')}, {enrichment_str} --style raw"

        # 4. 保证基本前缀与纯净质量
        if not prompt.startswith("cinematic photorealistic 8k"):
            prompt = f"cinematic photorealistic 8k, {prompt}"

        # 规整连续逗号
        prompt = re.sub(r",\s*,+", ", ", prompt).strip(" ,")
        return prompt

    @classmethod
    def sanitize_dialogue_sound_action(
        cls,
        raw_dialogue: str | None,
        raw_action: str | None = None,
        raw_foley: str | None = None,
    ) -> tuple[str, str, str, str, list[str]]:
        """台词、拟音、动作三权分立清洗器。

        彻底阻断任何物理拟音、环境声学描述与舞台指示泄漏进 dialogue 字段，
        保证 TTS 引擎与字幕系统只接收纯净自然语言。

        :param raw_dialogue: 原始台词文本（可能混杂拟音、方圆括号舞台动作指示）
        :param raw_action: 原始动作与表演指示
        :param raw_foley: 原始物理拟音提示
        :return: (speaker_name, clean_dialogue, clean_phonetic, clean_action, foley_cues)
        """
        raw_dlg = str(raw_dialogue or "").strip()
        raw_act = str(raw_action or "").strip()
        raw_fol = str(raw_foley or "").strip()

        speaker_name = ""
        acting_cues: list[str] = []
        foley_cues: list[str] = []
        if raw_fol:
            foley_cues.append(raw_fol)

        # 1. 提取说话人（支持中英文冒号）
        dlg_body = raw_dlg
        if "：" in dlg_body or ":" in dlg_body:
            sep = "：" if "：" in dlg_body else ":"
            candidate_spk, remainder = dlg_body.split(sep, 1)
            candidate_spk = candidate_spk.strip()
            # 提取并剔除说话人内部括号修饰，如 "陆沉(冷笑)" -> "陆沉"
            for sp in re.findall(r"[（\(](.*?)[）\)]", candidate_spk):
                if sp.strip():
                    acting_cues.append(sp.strip())
            candidate_spk = re.sub(r"[（\(].*?[）\)]", "", candidate_spk).strip()
            if candidate_spk and len(candidate_spk) <= 12:
                speaker_name = candidate_spk
                dlg_body = remainder.strip()

        # 拟音关键词黑名单模式
        foley_pattern = re.compile(
            r"(Braam|Whoosh|Creak|Slam|Rumble|Scrape|Whistling|Glass|Wind|Sound|Impact|Clatter|Footsteps|"
            r"阴风|呼啸|玻璃|碎裂|脚步声|雷声|风声|水滴|撞击|门响|回声|音效|拟音|SFX|BGM|OS|环境音)",
            re.IGNORECASE,
        )

        # 2. 提取并剥离方括号指示 [ ] 【 】
        for bracket_content in re.findall(r"[\[【](.*?)[\]】]", dlg_body):
            b_clean = bracket_content.strip()
            if b_clean:
                if foley_pattern.search(b_clean) or any(k in b_clean.lower() for k in ("sfx", "sound", "foley")):
                    foley_cues.append(b_clean)
                else:
                    acting_cues.append(b_clean)
        dlg_body = re.sub(r"[\[【].*?[\]】]", "", dlg_body)

        # 3. 提取并剥离圆括号指示 ( ) （ ）
        for p_content in re.findall(r"[（\(](.*?)[）\)]", dlg_body):
            p_clean = p_content.strip()
            if p_clean:
                if foley_pattern.search(p_clean):
                    foley_cues.append(p_clean)
                else:
                    acting_cues.append(p_clean)
        dlg_body = re.sub(r"[（\(].*?[）\)]", "", dlg_body)

        # 4. 检查正文剩余部分是否本身就是拟音描述
        clean_dialogue = dlg_body.lstrip("：: ").strip()
        if clean_dialogue:
            is_pure_foley = False
            if re.match(r"^(音效|拟音|SFX|BGM|环境音)\s*[:：]", clean_dialogue, re.IGNORECASE):
                is_pure_foley = True
            elif foley_pattern.search(clean_dialogue) and not any(k in clean_dialogue for k in ("我", "你", "他", "她", "这", "那", "不", "在", "是", "有")):
                is_pure_foley = True

            if is_pure_foley:
                foley_cues.append(clean_dialogue)
                clean_dialogue = ""

        # 清洗纯净台词只剩无意义标点的情况
        if clean_dialogue and re.match(r"^[\s\.,，。！？!?\-_/\\:：…~—]*$", clean_dialogue):
            clean_dialogue = ""

        # 5. 纯发音文本（供 TTS 引擎）
        clean_phonetic = ""
        if clean_dialogue:
            clean_phonetic = re.sub(r"[^\w\u4e00-\u9fa5，。！？,\.\?!]", "", clean_dialogue).strip()

        # 6. 动作与微表情融合
        combined_action = raw_act
        if acting_cues:
            cues_str = "，".join(dict.fromkeys(acting_cues))
            if not combined_action:
                combined_action = f"（{cues_str}）"
            elif cues_str not in combined_action:
                combined_action = f"{combined_action}（{cues_str}）"

        dedup_foley = list(dict.fromkeys(foley_cues))
        foley_str = " ".join(dedup_foley) if dedup_foley else ""
        logger.debug(
            "【台词三权分立清洗】speaker=%s, pure_dlg='%s', foley='%s', action='%s'",
            speaker_name, clean_dialogue, foley_str, combined_action
        )
        return clean_dialogue, foley_str, combined_action

    @classmethod
    def resolve_framing_asset_routing(
        cls,
        framing: str = "",
        scene_assets: dict[str, Any] | list[Any] | None = None,
        character_asset_ids: list[str] | None = None,
        prop_asset_ids: list[str] | None = None,
        primary_focus: str = "AUTO",
        shot_framing: str = "",
        scene_asset_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """根据分镜景别 (framing) 与视觉主体，自适应计算多模态底图引用优先级与背景虚化指令。

        【景别决策矩阵】：
        - ECU (极特写) / MACRO: 阻断 WIDE 全景大底图，调度 100mm 微距浅焦镜头 (f/1.8)，若无微观图则使用虚化背景；焦点锁定在核心物证或面部。
        - CU (特写) / CLOSE_UP: 优先匹配 Z01 局部子机位图；若无则使用 85mm 浅景深 (f/2.0) 聚焦主体，背景柔和虚化。
        - MCU / MS (中景): 50mm 标准镜头，平衡角色半身与空间置景交互。
        - FS / WS (全景/远景): 强制匹配 WIDE 全景大底图 (28mm 变形宽银幕)，deep focus 大景深。

        :return: 包含 camera_lens_directive, background_treatment, preferred_scene_view_type 等路由参数字典
        """
        framing_val = framing or shot_framing or ""
        framing_up = str(framing_val).strip().upper()
        chars = character_asset_ids or []
        props = prop_asset_ids or []

        if scene_assets is None and scene_asset_id:
            scene_assets = {"WIDE": scene_asset_id}

        is_ecu = any(k in framing_up for k in ("ECU", "EXTREME CLOSE", "MACRO", "极特写", "微距"))
        is_cu = not is_ecu and any(k in framing_up for k in ("CU", "CLOSE", "特写", "CLOSE-UP"))
        is_mcu_ms = any(k in framing_up for k in ("MCU", "MS", "MEDIUM", "中景", "半身"))
        is_wide = any(k in framing_up for k in ("WIDE", "WS", "FS", "ESTABLISH", "全景", "远景", "大全景"))

        scene_views: dict[str, str] = {}
        if isinstance(scene_assets, dict):
            for k, v in scene_assets.items():
                scene_views[str(k).upper()] = str(v)
        elif isinstance(scene_assets, list):
            for s in scene_assets:
                if isinstance(s, dict):
                    sid = str(s.get("asset_id") or s.get("scene_token") or "")
                    if "WIDE" in sid:
                        scene_views["WIDE"] = sid
                    elif "Z01" in sid or "ZONE" in sid:
                        scene_views["ZONE"] = sid

        focus = primary_focus.upper() if primary_focus != "AUTO" else "AUTO"
        if focus == "AUTO":
            if is_ecu:
                focus = "PROP" if props else ("CHAR" if chars else "DETAIL")
            elif is_cu:
                focus = "CHAR" if chars else ("PROP" if props else "ZONE")
            else:
                focus = "ENV" if is_wide else ("CHAR" if chars else "ENV")

        if is_ecu:
            camera_lens = "100mm macro lens, ultra-shallow depth of field f/1.8, razor-sharp focus on subject micro-texture"
            bg_treatment = "deeply defocused background with smooth cinematic bokeh, completely isolating the focal subject"
            preferred_view = "MACRO" if "MACRO" in scene_views else ("ZONE" if "ZONE" in scene_views else "BLURRED_ENV")
            allow_wide_background = False
        elif is_cu:
            camera_lens = "85mm portrait prime lens, shallow depth of field f/2.0, precise focal plane on key subject"
            bg_treatment = "softly blurred background atmosphere, environmental colors preserved without distracting details"
            preferred_view = "ZONE" if "ZONE" in scene_views else "WIDE"
            allow_wide_background = False
        elif is_mcu_ms:
            camera_lens = "50mm standard cinematic prime lens, f/4.0 balanced depth of field, clear foreground-to-midground hierarchy"
            bg_treatment = "natural perspective falloff, contextual interior geometry clearly legible"
            preferred_view = "ZONE" if "ZONE" in scene_views else "WIDE"
            allow_wide_background = True
        else:
            camera_lens = "28mm wide-angle anamorphic lens, deep focus f/8.0, expansive grand spatial perspective"
            bg_treatment = "crisp environmental architecture, deep spatial layers from foreground to background fully rendered"
            preferred_view = "WIDE"
            allow_wide_background = True

        logger.debug(
            "【景别自适应路由决策】framing=%s -> focus=%s, view=%s, allow_wide=%s, lens=%s",
            framing, focus, preferred_view, allow_wide_background, camera_lens[:45]
        )

        return {
            "framing": framing,
            "primary_focus": focus,
            "camera_lens_directive": camera_lens,
            "background_treatment": bg_treatment,
            "preferred_scene_view_type": preferred_view,
            "allow_wide_background": allow_wide_background,
        }

    @classmethod
    def compile_storyboard_multimodal_slots(
        cls,
        shot_dict: dict[str, Any],
        known_chars_list: list[dict[str, Any]] | None = None,
        known_props_list: list[dict[str, Any]] | None = None,
        routing_plan: dict[str, Any] | None = None,
        raw_image_prompt: str = "",
        raw_video_prompt: str = "",
        chars_catalog: list[dict[str, Any]] | None = None,
        props_catalog: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """权威视觉与音频槽位分配与正文图号双向一致性对齐器（彻底消灭幽灵图号）。

        【对齐与自愈核心机制】：
        1. 收集归一化资产：Scene (ENV_), Characters (CHAR_), Props (PROP_)，总槽位上限 4；
        2. 正文图号扫描与合法性检验：检测提示词中引用的所有 `图X`；
        3. 幽灵图号自愈两级策略：
           - 策略 A（同名词逆向匹配与补齐）：如果正文中出现了未在当前 media_manifest.images 声明的图号，
             若槽位未满 (< 4)，从已知资产库逆向补齐注册；
           - 策略 B（槽位投影与两阶段重写）：若槽位已满或该资产已在其他槽位，使用两阶段占位符安全重写；
           - 策略 C（安全降级）：若引用的图号完全属于越界无主引用（如正文突兀出现"图5"），自动剥离"图5"前缀；
        4. 保证 media_manifest.images 与提示词正文 100% 吻合。
        """
        known_chars_list = known_chars_list or chars_catalog or []
        known_props_list = known_props_list or props_catalog or []

        if raw_image_prompt and not shot_dict.get("image_prompt"):
            shot_dict["image_prompt"] = raw_image_prompt
        if raw_video_prompt and not shot_dict.get("video_prompt"):
            shot_dict["video_prompt"] = raw_video_prompt

        flc = shot_dict.get("first_last_config") if isinstance(shot_dict.get("first_last_config"), dict) else {}
        mic = shot_dict.get("multi_image_config") if isinstance(shot_dict.get("multi_image_config"), dict) else {}
        mm = mic.get("media_manifest") if isinstance(mic.get("media_manifest"), dict) else {}

        def _canonicalize_asset_id(raw_id: Any, default_category: str = "CHAR") -> str:
            if not raw_id:
                return ""
            valid, _ = AssetProtocolHelper.validate_id(raw_id)
            if valid:
                return AssetProtocolHelper.normalize_id(raw_id)

            norm = AssetProtocolHelper.normalize_id(raw_id)
            valid, _ = AssetProtocolHelper.validate_id(norm)
            if valid:
                return norm

            cat = default_category
            if norm.startswith("ENV_") or norm.startswith("SCENE_"):
                cat = "ENV"
                norm = re.sub(r"^(ENV_|SCENE_)", "", norm)
            elif norm.startswith("CHAR_"):
                cat = "CHAR"
                norm = re.sub(r"^CHAR_", "", norm)
            elif norm.startswith("PROP_"):
                cat = "PROP"
                norm = re.sub(r"^PROP_", "", norm)
            elif norm.startswith("VOICE_"):
                cat = "VOICE"
                norm = re.sub(r"^VOICE_", "", norm)

            tok = AssetProtocolHelper.chinese_to_token(norm) or norm or "ASSET"
            if cat == "ENV":
                return f"ENV_{tok}_T1_WIDE"
            elif cat == "PROP":
                return f"PROP_{tok}_T1_STATIC"
            elif cat == "VOICE":
                return f"VOICE_{tok}_T1_MASTER"
            else:
                return f"CHAR_{tok}_T1_BASE_PORTRAIT"

        if flc.get("first_frame_asset_id"):
            flc["first_frame_asset_id"] = _canonicalize_asset_id(flc["first_frame_asset_id"], "CHAR")
        if flc.get("last_frame_asset_id"):
            last_cat = "PROP" if "PROP_" in str(flc["last_frame_asset_id"]).upper() else "CHAR"
            flc["last_frame_asset_id"] = _canonicalize_asset_id(flc["last_frame_asset_id"], last_cat)
        if flc.get("first_frame_asset_ref"):
            flc["first_frame_asset_ref"] = flc.get("first_frame_asset_id") or _canonicalize_asset_id(flc["first_frame_asset_ref"], "CHAR")
        if flc.get("last_frame_asset_ref"):
            flc["last_frame_asset_ref"] = flc.get("last_frame_asset_id") or _canonicalize_asset_id(flc["last_frame_asset_ref"], "PROP")

        # 收集现有引用
        raw_scene = str(shot_dict.get("scene_asset_id") or "")
        char_ids: list[str] = [str(c) for c in (shot_dict.get("character_asset_ids") or []) if c]
        prop_ids: list[str] = [str(p) for p in (shot_dict.get("prop_asset_ids") or []) if p]

        raw_scene = _canonicalize_asset_id(raw_scene, "ENV") or "ENV_DEFAULT_STAGE6_T1_WIDE"
        char_ids = [_canonicalize_asset_id(c, "CHAR") for c in char_ids if c]
        prop_ids = [_canonicalize_asset_id(p, "PROP") for p in prop_ids if p]

        def _dedup_list(items: list[str]) -> list[str]:
            seen = set()
            out = []
            for item in items:
                if item and item not in seen:
                    seen.add(item)
                    out.append(item)
            return out

        char_ids = _dedup_list(char_ids)
        prop_ids = _dedup_list(prop_ids)

        # 文本扫描兜底补齐资产
        combined_text = " ".join([
            str(shot_dict.get("image_prompt") or ""),
            str(shot_dict.get("video_prompt") or ""),
            str(shot_dict.get("action") or ""),
            str((shot_dict.get("audio") or {}).get("dialogue") or ""),
            str((shot_dict.get("audio") or {}).get("foley") or ""),
        ])

        if known_props_list:
            for p_item in known_props_list:
                if not isinstance(p_item, dict):
                    continue
                p_name = str(p_item.get("name") or p_item.get("prop_name") or "").strip()
                p_aliases = p_item.get("aliases") or []
                if (p_name and len(p_name) >= 2 and p_name in combined_text) or any(
                    isinstance(a, str) and len(a) >= 2 and a in combined_text for a in p_aliases
                ):
                    raw_pid = (
                        p_item.get("asset_id")
                        or p_item.get("benchmark_asset_key")
                        or p_item.get("prop_id")
                        or (f"PROP_{p_item.get('prop_token')}_T1_STATIC" if p_item.get("prop_token") else None)
                        or f"PROP_{AssetProtocolHelper.chinese_to_token(p_name)}_T1_STATIC"
                    )
                    norm_pid = _canonicalize_asset_id(str(raw_pid), "PROP")
                    if norm_pid and norm_pid not in prop_ids:
                        prop_ids.append(norm_pid)

        if known_chars_list:
            for c_item in known_chars_list:
                if not isinstance(c_item, dict):
                    continue
                c_name = str(c_item.get("name") or c_item.get("character_name") or "").strip()
                if c_name and len(c_name) >= 2 and c_name in combined_text:
                    raw_cid = (
                        c_item.get("asset_id")
                        or c_item.get("benchmark_asset_key")
                        or c_item.get("character_id")
                        or (f"CHAR_{c_item.get('character_token')}_T1_BASE_PORTRAIT" if c_item.get("character_token") else None)
                        or f"CHAR_{AssetProtocolHelper.chinese_to_token(c_name)}_T1_BASE_PORTRAIT"
                    )
                    norm_cid = _canonicalize_asset_id(str(raw_cid), "CHAR")
                    if norm_cid and norm_cid not in char_ids:
                        char_ids.append(norm_cid)

        # 说话人优先排在角色第一位（确保图2永远为说话主体，图3为同框倾听/对手）
        audio_obj = shot_dict.get("audio") if isinstance(shot_dict.get("audio"), dict) else {}
        dlg_str = str(audio_obj.get("dialogue") or shot_dict.get("srt_text") or "").strip()
        speaker_name = ""
        lipsync_obj = shot_dict.get("lipsync_dynamics") if isinstance(shot_dict.get("lipsync_dynamics"), dict) else {}
        if lipsync_obj.get("speaker"):
            speaker_name = str(lipsync_obj.get("speaker")).strip()
        if not speaker_name and audio_obj.get("speaker"):
            speaker_name = str(audio_obj.get("speaker")).strip()
        if not speaker_name and shot_dict.get("speaker"):
            speaker_name = str(shot_dict.get("speaker")).strip()
        if not speaker_name:
            if "：" in dlg_str:
                speaker_name = dlg_str.split("：", 1)[0].strip()
            elif ":" in dlg_str:
                speaker_name = dlg_str.split(":", 1)[0].strip()

        if speaker_name and known_chars_list:
            for c_item in known_chars_list:
                if not isinstance(c_item, dict):
                    continue
                c_name = str(c_item.get("name") or c_item.get("character_name") or "").strip()
                c_tok = str(c_item.get("character_token") or "").strip()
                c_id_raw = str(c_item.get("character_id") or c_item.get("asset_id") or "").strip()
                is_match = False
                if c_name and (c_name == speaker_name or c_name in speaker_name or speaker_name in c_name):
                    is_match = True
                elif c_tok and (c_tok.upper() == speaker_name.upper() or c_tok.upper() in speaker_name.upper()):
                    is_match = True
                elif c_id_raw and (c_id_raw == speaker_name or speaker_name in c_id_raw):
                    is_match = True

                if is_match:
                    raw_spk = (
                        c_item.get("asset_id")
                        or c_item.get("benchmark_asset_key")
                        or c_item.get("character_id")
                        or (f"CHAR_{c_tok}_T1_BASE_PORTRAIT" if c_tok else None)
                        or f"CHAR_{AssetProtocolHelper.chinese_to_token(c_name)}_T1_BASE_PORTRAIT"
                    )
                    spk_cid = _canonicalize_asset_id(str(raw_spk), "CHAR")
                    if spk_cid in char_ids:
                        char_ids.remove(spk_cid)
                    char_ids.insert(0, spk_cid)
                    logger.debug(
                        "【说话人槽位首发对齐】shot_id=%s 将说话主体 %s (%s) 提升至角色槽位首位 (图2)",
                        shot_dict.get("shot_id"), speaker_name, spk_cid
                    )
                    break

        # 景别路由约束：若为 ECU 极特写，且首要焦点为道具，可将道具置于最前
        plan = routing_plan or {}
        allow_wide = plan.get("allow_wide_background", True)
        if not allow_wide and not raw_scene.endswith(("_Z01", "_ZONE", "_MACRO")):
            # 极特写时，若原 scene 为 WIDE 全景，降级为局部微环境标识
            raw_scene = raw_scene.replace("_WIDE", "_MACRO") if "_WIDE" in raw_scene else f"{raw_scene}_MACRO"

        # 分配权威槽位（最多 4 个）
        canonical_images: list[dict[str, Any]] = []
        canonical_images.append({
            "slot_order": 1,
            "symbol": "图1",
            "asset_id": raw_scene or "ENV_DEFAULT_STAGE6",
            "role": "核心场景环境",
        })

        max_char_slots = 2 if (prop_ids and len(char_ids) >= 3) else 3
        selected_chars = char_ids[:max_char_slots]
        remaining_slots = 4 - 1 - len(selected_chars)
        selected_props = prop_ids[:max(0, remaining_slots)]

        for idx_c, cid in enumerate(selected_chars):
            s_num = len(canonical_images) + 1
            canonical_images.append({
                "slot_order": s_num,
                "symbol": f"图{s_num}",
                "asset_id": cid,
                "role": "角色主体" if idx_c == 0 else f"出场角色{idx_c + 1}",
            })

        for idx_p, pid in enumerate(selected_props):
            s_num = len(canonical_images) + 1
            canonical_images.append({
                "slot_order": s_num,
                "symbol": f"图{s_num}",
                "asset_id": pid,
                "role": f"交互物证道具{idx_p + 1}",
            })

        # 扫描正文已引用的图号（如 图1, 图2, 图3...）
        prompts_to_check = [
            ("image_prompt", str(shot_dict.get("image_prompt") or "")),
            ("video_prompt", str(shot_dict.get("video_prompt") or "")),
        ]
        if flc.get("video_motion_prompt"):
            prompts_to_check.append(("first_last_config.video_motion_prompt", str(flc["video_motion_prompt"])))

        # 当前合法已声明的图号集合
        valid_symbols = {img["symbol"] for img in canonical_images}
        max_valid_slot = len(canonical_images)

        # 建立资产到当前合法图号的映射
        asset_to_symbol: dict[str, str] = {img["asset_id"]: img["symbol"] for img in canonical_images}

        # 检测提示词中的越界或幽灵图号
        symbol_remap: dict[str, str] = {}
        for p_key, p_text in prompts_to_check:
            found_slots = re.findall(r"图([1-9])", p_text)
            for s_str in found_slots:
                sym = f"图{s_str}"
                s_int = int(s_str)
                if sym not in valid_symbols:
                    # 发现幽灵图号！
                    # 检查此图号后面是否紧跟已知实体名，例如 "图3牛皮纸信封"
                    m_entity = re.search(rf"{sym}([\u4e00-\u9fa5A-Za-z0-9_]{{2,8}})", p_text)
                    remapped_to = ""
                    if m_entity:
                        ent_name = m_entity.group(1)
                        # 查找该实体是否已经分配在其他图号中
                        for img in canonical_images:
                            aid = img["asset_id"].upper()
                            if ent_name.upper() in aid or any(
                                p_item.get("name") == ent_name and p_item.get("asset_id") == img["asset_id"]
                                for p_item in (known_props_list or [])
                                if isinstance(p_item, dict)
                            ):
                                remapped_to = img["symbol"]
                                break
                    if not remapped_to and m_entity:
                        ent_name = m_entity.group(1)
                        # 检查是否匹配已知未入槽的真实道具或角色
                        matched_real_aid = ""
                        matched_role = ""
                        if known_props_list:
                            for p_item in known_props_list:
                                if not isinstance(p_item, dict):
                                    continue
                                p_n = str(p_item.get("name") or "")
                                if p_n and (p_n in ent_name or ent_name in p_n):
                                    raw_pid = (
                                        p_item.get("asset_id")
                                        or p_item.get("prop_id")
                                        or (f"PROP_{p_item.get('prop_token')}_T1_STATIC" if p_item.get("prop_token") else None)
                                        or f"PROP_{AssetProtocolHelper.chinese_to_token(p_n)}_T1_STATIC"
                                    )
                                    matched_real_aid = _canonicalize_asset_id(str(raw_pid), "PROP")
                                    matched_role = f"已知物证道具: {p_n}"
                                    break
                        if not matched_real_aid and known_chars_list:
                            for c_item in known_chars_list:
                                if not isinstance(c_item, dict):
                                    continue
                                c_n = str(c_item.get("name") or "")
                                if c_n and (c_n in ent_name or ent_name in c_n):
                                    raw_cid = (
                                        c_item.get("asset_id")
                                        or c_item.get("character_id")
                                        or (f"CHAR_{c_item.get('character_token')}_T1_BASE_PORTRAIT" if c_item.get("character_token") else None)
                                        or f"CHAR_{AssetProtocolHelper.chinese_to_token(c_n)}_T1_BASE_PORTRAIT"
                                    )
                                    matched_real_aid = _canonicalize_asset_id(str(raw_cid), "CHAR")
                                    matched_role = f"已知角色主体: {c_n}"
                                    break

                        if matched_real_aid and len(canonical_images) < 4:
                            new_slot = len(canonical_images) + 1
                            new_sym = f"图{new_slot}"
                            canonical_images.append({
                                "slot_order": new_slot,
                                "symbol": new_sym,
                                "asset_id": matched_real_aid,
                                "role": matched_role,
                            })
                            valid_symbols.add(new_sym)
                            remapped_to = new_sym

                    if not remapped_to:
                        # 严禁将中文词组随意哈希或拼接成伪造资产 ID (如 PROP_SHENMOLIAN...)
                        # 幽灵图号安全重定向至最相关的合法槽位（图2角色或图1场景）
                        remapped_to = f"图{min(s_int, max_valid_slot)}" if max_valid_slot > 0 else "图1"

                    symbol_remap[sym] = remapped_to
                    logger.debug(
                        "【幽灵图号拦截自愈】shot_id=%s 在 %s 中检测到幽灵图号 %s，自动安全重定向至 %s",
                        shot_dict.get("shot_id"), p_key, sym, remapped_to
                    )

        # 两阶段安全替换
        if symbol_remap:
            def _rewrite_safe(text_val: str) -> str:
                if not text_val:
                    return text_val
                tmp = text_val
                for i, (old_s, _) in enumerate(symbol_remap.items()):
                    tmp = tmp.replace(old_s, f"__SLOT_TMP_{i}__")
                for i, (_, new_s) in enumerate(symbol_remap.items()):
                    tmp = tmp.replace(f"__SLOT_TMP_{i}__", new_s)
                return tmp

            shot_dict["image_prompt"] = _rewrite_safe(str(shot_dict.get("image_prompt") or ""))
            shot_dict["video_prompt"] = _rewrite_safe(str(shot_dict.get("video_prompt") or ""))
            if flc.get("video_motion_prompt"):
                flc["video_motion_prompt"] = _rewrite_safe(str(flc["video_motion_prompt"]))
        else:
            shot_dict["image_prompt"] = str(shot_dict.get("image_prompt") or raw_image_prompt or "")
            shot_dict["video_prompt"] = str(shot_dict.get("video_prompt") or raw_video_prompt or "")

        # 构建权威音频槽位
        audio_obj = shot_dict.get("audio") if isinstance(shot_dict.get("audio"), dict) else {}
        dialogue_val = str(audio_obj.get("dialogue") or shot_dict.get("dialogue") or "").strip()
        music_val = str(audio_obj.get("music") or shot_dict.get("music_cue") or "").strip()
        foley_val = str(audio_obj.get("foley") or shot_dict.get("foley_cue") or "").strip()

        canonical_audios: list[dict[str, Any]] = []
        if dialogue_val:
            canonical_audios.append({
                "slot_order": 1,
                "symbol": "音频1",
                "track_type": "dialogue",
                "description": f"主对白驱动音轨: {dialogue_val}",
            })
        if foley_val:
            canonical_audios.append({
                "slot_order": len(canonical_audios) + 1,
                "symbol": f"音频{len(canonical_audios) + 1}",
                "track_type": "foley",
                "description": f"物证据动/动作拟音: {foley_val}",
            })
        if music_val:
            canonical_audios.append({
                "slot_order": len(canonical_audios) + 1,
                "symbol": f"音频{len(canonical_audios) + 1}",
                "track_type": "bgm",
                "description": f"场景情绪配乐: {music_val}",
            })

        # 回填与同步
        ref_ids = [img["asset_id"] for img in canonical_images]
        shot_dict["scene_asset_id"] = canonical_images[0]["asset_id"] if canonical_images else "ENV_WIDE"
        shot_dict["character_asset_ids"] = [img["asset_id"] for img in canonical_images if str(img.get("asset_id", "")).startswith("CHAR_")]
        shot_dict["prop_asset_ids"] = [img["asset_id"] for img in canonical_images if str(img.get("asset_id", "")).startswith("PROP_")]
        shot_dict["canonical_visual_slots"] = canonical_images
        shot_dict["canonical_audio_slots"] = canonical_audios
        shot_dict["_canonical_visual_slots"] = canonical_images
        shot_dict["_canonical_audio_slots"] = canonical_audios
        shot_dict["reference_asset_ids"] = ref_ids

        if not isinstance(shot_dict.get("multi_image_config"), dict):
            shot_dict["multi_image_config"] = {}
        shot_dict["multi_image_config"]["media_manifest"] = {
            "images": canonical_images,
            "audios": canonical_audios,
        }
        shot_dict["multi_image_config"]["reference_asset_ids"] = ref_ids

        return shot_dict

    @classmethod
    def synthesize_engine_video_prompt(
        cls,
        shot_dict: dict[str, Any] | None = None,
        target_engine: str = "wan3.0",
        action_verbs: str = "",
        scene_symbol: str = "图1",
        subject_symbol: str = "图2",
        counterpart_symbol: str | None = None,
        prop_symbol: str | None = None,
        dialogue_audio_symbol: str | None = None,
        ambient_sound: str | None = None,
        foley_sound: str | None = None,
        max_words: int = 80,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        """视频提示词双轨精炼器（渲染执行轨 vs 工程元数据轨）。

        【双轨架构】：
        1. 渲染执行轨 (engine_video_prompt)：
           - 面向指定视频生成底模（Wan 3.0 / Seedance 2.5 / MiniMax H3）组装精确动作流与机位；
           - 严格控制在 80 个英文单词（或 120 个汉字）以内；
           - 坚决剔除任何声学指令违规扩散与排他负向词。
        2. 工程元数据轨 (engineering_manifest)：
           - 沉淀声学铺底、动作拟音、闭嘴防穿帮约束与槽位清单为结构化字典。

        :return: (engine_video_prompt, engineering_manifest)
        """
        # 若传入了 shot_dict，提取缺省字段
        if isinstance(shot_dict, dict):
            target_engine = str(shot_dict.get("target_engine") or target_engine or "wan3.0")
            if not action_verbs:
                flc = shot_dict.get("first_last_config") if isinstance(shot_dict.get("first_last_config"), dict) else {}
                action_verbs = str(shot_dict.get("video_prompt") or flc.get("video_motion_prompt") or shot_dict.get("dynamic_cue") or "")
            audio_info = shot_dict.get("audio") if isinstance(shot_dict.get("audio"), dict) else {}
            if ambient_sound is None:
                ambient_sound = str(audio_info.get("music") or shot_dict.get("music_cue") or "").strip() or None
            if foley_sound is None:
                foley_sound = str(audio_info.get("foley") or shot_dict.get("foley_cue") or "").strip() or None

        if kwargs.get("action_dynamics") and not action_verbs:
            action_verbs = str(kwargs["action_dynamics"])
        if kwargs.get("camera_movement"):
            cam_mov = str(kwargs["camera_movement"])
            action_verbs = f"[{cam_mov}]，{action_verbs}" if action_verbs else f"[{cam_mov}]"
        if kwargs.get("visual_slots"):
            for slot in kwargs["visual_slots"]:
                if not isinstance(slot, dict):
                    continue
                role = str(slot.get("role") or slot.get("interaction_role") or "").lower()
                sym = str(slot.get("symbol", ""))
                aid = str(slot.get("asset_id", "")).upper()
                if "scene" in role or "background" in role or aid.startswith(("ENV_", "SCENE_")):
                    scene_symbol = sym
                elif "focus" in role or "prop" in role or aid.startswith("PROP_"):
                    prop_symbol = sym
                elif "subject" in role or "primary" in role or "character" in role or aid.startswith("CHAR_"):
                    if not subject_symbol or subject_symbol == "图2":
                        subject_symbol = sym
                    else:
                        counterpart_symbol = sym

        eng = (target_engine or "wan3.0").lower().strip()
        # 清洗动作描述中的禁忌修饰词与冗余/冲突的方括号参考图协议头
        clean_action = re.sub(r"\[(首要参考|主要参考|核心参考|画中物证|交互物证|参考图|镜头运动|景别)[^\]]*\]", "", action_verbs)
        clean_action = re.sub(r"(无肢体畸变|无五官崩坏|无画面抖动|电影级画质|8k|masterpiece)", "", clean_action, flags=re.IGNORECASE)
        clean_action = re.sub(r"\s+", " ", clean_action).strip(" ，,。.")

        clean_foley = ""
        if foley_sound:
            clean_foley = foley_sound.replace("[Foley+3dB:", "").replace("]", "").strip()

        if "seedance" in eng:
            # Seedance 2.5 模块化分段
            subj_part = f"[Subject] {subject_symbol}" + (f" 与 {counterpart_symbol} 对峙" if counterpart_symbol else "")
            if prop_symbol:
                subj_part += f"，手中紧握物证 {prop_symbol}"
            env_part = f"[Environment] 在 {scene_symbol} 空间中"
            if ambient_sound:
                env_part += f"，环境空间声场铺底（{ambient_sound}）"
            env_part += "，光影明暗交界清晰"
            act_part = f"[Action] {clean_action}"
            if clean_foley:
                act_part += f"，物理动作伴随拟音爆发（{clean_foley}）"
            if dialogue_audio_symbol:
                act_part += f"，[说话主体: {subject_symbol}] 同步开口说话（{dialogue_audio_symbol}）"
            if counterpart_symbol:
                act_part += f"，[倾听角色: {counterpart_symbol}] 紧闭双唇保持静默、不发一言"
            cam_part = "[Camera] 固定冷峻凝视，景别保持中近景，无肢体畸变、无五官崩坏、无画面抖动"
            res = f"{subj_part}。{env_part}。{act_part}。{cam_part}。"
        elif "minimax" in eng:
            # MiniMax H3 自然语言叙述流
            res = f"在 {scene_symbol} 空间中"
            if ambient_sound:
                res += f"（空间弥漫着{ambient_sound}）"
            res += f"，{subject_symbol}"
            if counterpart_symbol:
                res += f" 逼视着 {counterpart_symbol}，"
            res += f" {clean_action}"
            if prop_symbol:
                res += f"，手中紧握物证 {prop_symbol}"
            if clean_foley:
                res += f"，动作爆发伴随物理接触音（{clean_foley}）"
            if dialogue_audio_symbol:
                res += f"，[说话主体: {subject_symbol}] 低沉开口说道（{dialogue_audio_symbol}）"
            if counterpart_symbol:
                res += f"，同框 [同伴: {counterpart_symbol}] 紧闭双唇保持肃穆无言"
            res += "。情绪连贯克制，无肢体畸变、无五官崩坏、无画面抖动。"
        else:
            # Wan 3.0 物理光影与动态细节 (默认)
            res = f"在 {scene_symbol} 环境中"
            if ambient_sound:
                res += f"，空间声场铺底（{ambient_sound}）"
            res += "，光影反射在地面与墙壁。"
            res += f"{subject_symbol}"
            if counterpart_symbol:
                res += f" 与 {counterpart_symbol} 相对而立，"
            res += f" {clean_action}"
            if prop_symbol:
                res += f"，手中紧握物证 {prop_symbol}"
            if clean_foley:
                res += f"，伴随物理拟音音效（{clean_foley}）"
            if dialogue_audio_symbol:
                res += f"，[说话主体: {subject_symbol}] 开口叙述（{dialogue_audio_symbol}）"
            if counterpart_symbol:
                res += f"，同框 [倾听同伴: {counterpart_symbol}] 紧闭双唇、目光冰冷凝视、不发一言"
            res += "。电影级物理质感，无肢体畸变、无五官崩坏、无画面抖动。"

        engineering_manifest = {
            "target_engine": target_engine,
            "scene_symbol": scene_symbol,
            "subject_symbol": subject_symbol,
            "counterpart_symbol": counterpart_symbol,
            "prop_symbol": prop_symbol,
            "dialogue_audio_symbol": dialogue_audio_symbol,
            "acoustics": {
                "ambient": ambient_sound,
                "foley": foley_sound,
            },
            "lipsync_and_silence": {
                "speaker": subject_symbol if dialogue_audio_symbol else None,
                "silent_listener": counterpart_symbol,
            },
        }

        logger.debug(
            "【视频提示词双轨精炼】engine=%s, vp_len=%d, subject=%s, counterpart=%s",
            target_engine, len(res), subject_symbol, counterpart_symbol
        )
        return res, engineering_manifest


class PromptMatrixSynthesizer:
    """毫秒级本地规则矩阵生图提示词合成引擎 (PromptMatrixSynthesizer)。
    
    严格依据 Diffusion 与 Flow-Matching 模型 Token 黄金位置衰减规律（Positional Decay），
    实施五级插槽拼装（Slot-Priority Composition）：
    - Slot 0 [P0: 核心主体人种/国籍]: 锁定东亚/中国/韩国自然面孔，绝不脸崩洋化；
    - Slot 1 [P1: 时代世界观与建筑材质]: 具象解构时代物证（如80年代中国红砖筒子楼、剥落绿墙裙等）；
    - Slot 2 [P2: 剧情微观物理动态与战损]: 融入 Step 1 纯剧本盲抽抽取的流血伤口、浸湿衣服、咬牙切齿；
    - Slot 3 [P3: 摄影光学与构图视角]: 角色绑定 85mm 人像，场景绑定 35mm 变形宽银幕，道具 100mm 微距；
    - Slot 4 [P4: 全局视觉影调展开]: 真实展开 visual_style，彻底消灭 [visual_style] 占位符。
    """

    ETHNICITY_MAP: dict[str, str] = {
        "chinese": "Authentic East Asian Chinese face, natural skin texture, distinct Chinese facial features, realistic natural eyelids",
        "korean": "Authentic East Asian Korean face, natural clean skin texture, distinct Korean facial aesthetics",
        "japanese": "Authentic East Asian Japanese face, natural skin tone, distinct Japanese facial structure",
        "default": "Authentic East Asian face, distinct natural features, realistic skin texture with visible fine pores",
    }

    PERIOD_ARCHITECTURE_MAP: dict[str, str] = {
        "1980s_china": "1980s mainland China, weathered red-brick residential dormitory building (筒子楼), aged industrial factory housing, narrow outdoor concrete walkway with rusted iron railings, peeling green paint on lower corridor walls, old bicycles parked against the wall, hanging cotton laundry on wire lines, retro thermos and enamel mugs on balcony",
        "1990s_china": "1990s China urban neighbourhood, weathered mosaic tile facade, aluminium window frames with burglar bars, nostalgic street signage, damp concrete floor, peeling posters on concrete poles, mottled grey walls with exposed wiring",
        "2000s_industrial_china": "Early 2000s northern China industrial town, weathered soot-stained factory district, dilapidated single-story brick courtyard houses with cracked cement tiles, dusty unpaved alleys, soot-darkened brick walls, vintage coal stoves and rusted bicycles, gritty realistic northern atmosphere",
        "jiangnan_water_town": "Traditional Jiangnan water town, black-tiled white-walled residential dwellings (粉墙黛瓦), weathered bluestone slab pathways, narrow canal alleyways, damp moss creeping along water-lapped stone foundations, gentle misty river atmosphere",
        "ming_wuxia": "Ming dynasty traditional interior, mortise and tenon dark aged elm wood architecture, paper lattice sliding windows, weathered celadon brick floor, muted historical cinematic textures",
        "modern_urban": "Contemporary urban city, rain-slicked asphalt reflecting cool neon signage, brutalist concrete facade, shadowy corridor",
    }

    # 电影级光学瑕疵与胶片质感基准词包 (消除 AI 平滑塑料假人感)
    CINEMATIC_OPTICAL_DIRECTIVES = (
        "shot on 35mm anamorphic prime lens, authentic 35mm film grain, subtle halation around bright light sources, "
        "natural optical depth of field with creamy bokeh, slight chromatic aberration at extreme frame edges, "
        "raw photographic texture, hyper-realistic skin texture with fine visible pores and micro-imperfections, "
        "no plastic smoothing, no beauty filter, no 3d render look"
    )

    @classmethod
    def resolve_ethnicity_token(cls, ethnicity_hint: str = "", character_name: str = "") -> str:
        """从角色人设或姓名中消解出黄金防漂移人种词包。"""
        hint = str(ethnicity_hint or "").lower()
        if "korean" in hint or "韩" in hint:
            return cls.ETHNICITY_MAP["korean"]
        elif "japan" in hint or "日" in hint:
            return cls.ETHNICITY_MAP["japanese"]
        elif "chinese" in hint or "中" in hint or "华" in hint:
            return cls.ETHNICITY_MAP["chinese"]
        return cls.ETHNICITY_MAP["chinese"]

    @classmethod
    def resolve_period_architecture(cls, visual_style: str = "", env_name: str = "", context_text: str = "") -> str:
        """从全剧视觉风格、场景名或上下文消解出具象时代建筑材质与本土特征。"""
        combined = f"{visual_style} {env_name} {context_text}".lower()
        if any(kw in combined for kw in ("80", "八十", "筒子楼", "红砖", "厂区", "国企", "老工")):
            return cls.PERIOD_ARCHITECTURE_MAP["1980s_china"]
        elif any(kw in combined for kw in ("90", "九十", "防盗网", "马赛克")):
            return cls.PERIOD_ARCHITECTURE_MAP["1990s_china"]
        elif any(kw in combined for kw in ("2000", "00", "老矿", "老宅", "旧居", "灵堂", "平房", "北方", "工业镇")):
            return cls.PERIOD_ARCHITECTURE_MAP["2000s_industrial_china"]
        elif any(kw in combined for kw in ("江南", "水乡", "青瓦", "粉墙", "乌镇")):
            return cls.PERIOD_ARCHITECTURE_MAP["jiangnan_water_town"]
        elif any(kw in combined for kw in ("明", "武侠", "古装", "客栈", "破庙", "江湖", "驿站", "仙侠", "修仙")):
            return cls.PERIOD_ARCHITECTURE_MAP["ming_wuxia"]
        
        # 室内场景防污染保护：若包含室内相关字眼，绝不降级为室外雨夜沥青霓虹街道
        if any(k in combined for k in ("室", "堂", "房", "屋", "居", "厅", "馆", "内", "殿", "阁", "舍", "仓", "楼", "interior")):
            return "Cinematic interior architectural space, realistic textural structural surfaces"

        return cls.PERIOD_ARCHITECTURE_MAP["modern_urban"]

    @classmethod
    def resolve_microclimate_tokens(cls, context_text: str = "") -> str:
        """根据场景光影/天气/季节线索提取具象微气候生理反应与空气悬浮介质。"""
        ctx_lower = context_text.lower()
        tokens: list[str] = []
        # 寒冷/室外雪夜/冬日微气候
        if any(kw in ctx_lower for kw in ("寒", "冬", "雪", "冷", "冻", "冰", "freezing", "snow", "winter", "cold")):
            tokens.append("visible white breath mist in freezing cold air, subtle wind-bitten red flush on nose and earlobes")
        # 潮湿/闷热/油汗微气候
        elif any(kw in ctx_lower for kw in ("潮湿", "燥热", "酷暑", "汗", "雨", "rain", "humid", "sweat")):
            tokens.append("subtle fine beads of perspiration on brow and temples, damp fabric clinging slightly to skin")
        # 室内尘封/灵堂/香烛空气介质
        if any(kw in ctx_lower for kw in ("灵堂", "旧居", "尘", "烟", "烛", "暗室", "dust", "incense", "smoke", "haze")):
            tokens.append("volumetric light beams cutting through air with drifting visible dust motes, soft lingering incense smoke haze")
        return ", ".join(tokens)

    # =========================================================================
    # 严格三级阶梯拓扑图 (DAG Execution) 专用提示词合成器
    # =========================================================================

    @classmethod
    def synthesize_tier1_face_prompt(
        cls,
        name: str,
        facial_dna: str,
        char_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """【Tier 1: 纯面部基准图 (t2i)】
        仅摄入 P_Face (纯五官骨相与皮肤微瑕)，在中性暗灰底板下提取纯净 FaceID，
        严格排除任何服饰、全身剪裁、鞋履、手势动作与外部环境。
        """
        prof = char_profile or {}
        bio = prof.get("biological_dna") or {}
        gender = prof.get("gender") or "person"
        ethnicity_hint = prof.get("ethnicity") or bio.get("ethnicity") or "chinese"
        p0_ethnicity = cls.resolve_ethnicity_token(ethnicity_hint, name)

        p_face = facial_dna or bio.get("bone_structure") or prof.get("appearance") or "structured cinematic facial bone structure, natural skin texture"

        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .replace("[placeholder]", "")
            .strip()
        )
        if not clean_style:
            clean_style = "cinematic film lighting, subtle 35mm grain, highly detailed 8k, photorealistic --style raw"

        tokens = [
            f"{p0_ethnicity}, {gender} {name}",
            f"Facial & Bone Anatomy: {p_face}",
            "single person, close-up frontal headshot portrait, 85mm portrait photography, 85mm portrait lens, eye-level framing",
            "neutral resting facial expression, shallow depth of field, razor sharp focus on eyes and facial skin micro-textures",
            "bare shoulders, visible collarbone and neck, completely isolated subject",
            "clean solid neutral dark gray studio photography backdrop, completely blank neutral dark gray studio photography backdrop, pure solid dark gray background",
            "zero environmental elements, zero clothing details, no jacket, no shirt, no background clutter",
            f"cinematic realism, {cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}",
        ]
        return ", ".join(t for t in tokens if t)

    @classmethod
    def synthesize_tier2_front_prompt(
        cls,
        name: str,
        facial_dna: str,
        physique_body: str,
        costume_material: str,
        char_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """【Tier 2.1: 正面全身图 (t2i + ControlNet OpenPose 强约束 + FaceID 注入 T1)】
        全面装配 P_Face (五官骨相) + P_Body (身形骨架与头身比) + P_Cloth (服装面料与鞋履)，
        强制注入头足完整性 (uncropped head-to-toe) 与地面接触真实阴影。
        """
        prof = char_profile or {}
        bio = prof.get("biological_dna") or {}
        gender = prof.get("gender") or "person"
        ethnicity_hint = prof.get("ethnicity") or bio.get("ethnicity") or "chinese"
        p0_ethnicity = cls.resolve_ethnicity_token(ethnicity_hint, name)

        p_face = facial_dna or bio.get("bone_structure") or "structured cinematic facial bone structure, natural skin texture"
        p_body = physique_body or "standard adult human proportions, upright posture, natural shoulder width"
        p_cloth = costume_material or prof.get("costume_specs") or "authentic period fabric, tailored fit, full length trousers and matching footwear"

        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .replace("[placeholder]", "")
            .strip()
        )
        if not clean_style:
            clean_style = "cinematic film lighting, subtle 35mm grain, highly detailed 8k, photorealistic --style raw"

        tokens = [
            f"{p0_ethnicity}, {gender} {name}",
            f"Facial & Bone Anatomy: {p_face}",
            f"Physique & Body Proportions: {p_body}",
            f"Costume & Fabrics: {p_cloth}",
            "full length front view portrait, standing upright pose, eye level, neutral posture, 50mm lens",
            "complete body from top of head to soles of shoes fully visible, uncropped head and uncropped feet",
            "clear negative space above head and below feet",
            "standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, soles visible",
            "clean solid neutral gray studio backplate, seamless seamless photo studio environment",
            f"cinematic realism, {cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}",
        ]
        return ", ".join(t for t in tokens if t)

    @classmethod
    def synthesize_tier2_view_prompt(
        cls,
        name: str,
        view_type: str,
        costume_material: str,
        char_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """【Tier 2.2: 侧面/背面/3Q 全身图 (i2i 垫图 T2.1，继承服装与体态)】
        以正面全身立绘为基准图执行图生图，聚焦视角旋转 (profile / back / 3/4) 与服装背侧面剪裁。
        """
        prof = char_profile or {}
        gender = prof.get("gender") or "person"
        vt = view_type.upper()

        if "PROFILE" in vt or "SIDE" in vt:
            view_desc = "full length 90-degree side profile view portrait, standing upright, side facing silhouette"
        elif "BACK" in vt:
            view_desc = "full length 180-degree back view portrait, standing upright facing away, rear costume details and back silhouette"
        elif "3Q" in vt or "THREE_QUARTER" in vt:
            view_desc = "full length three-quarter 45-degree angle view portrait, showing costume depth"
        else:
            view_desc = "full length turn-around view portrait, standing pose"

        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .replace("[placeholder]", "")
            .strip()
        )
        if not clean_style:
            clean_style = "cinematic film lighting, subtle 35mm grain, highly detailed 8k, photorealistic --style raw"

        tokens = [
            f"{gender} {name}",
            view_desc,
            f"Costume & Fabrics: {costume_material}",
            "complete body from head to toe, uncropped head, uncropped feet, shoes fully in frame",
            "standing firmly on concrete studio floor with realistic soft contact cast shadows under shoes, soles visible",
            "clean solid neutral gray studio backplate",
            f"cinematic realism, {cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}",
        ]
        return ", ".join(t for t in tokens if t)

    @classmethod
    def synthesize_tier3_face_inpaint_prompt(
        cls,
        name: str,
        expression_cues: str,
        char_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """【Tier 3.1: 微表情切片 (Inpaint 局部重绘 T1 面部)】
        以 T1 纯面部为底图，仅局部重绘面部肌肉张力与微表情。
        """
        tokens = [
            f"close-up facial expression portrait of {name}",
            f"micro-expression: {expression_cues}",
            "clenching facial muscles, dramatic facial lighting, intense eye reflection",
            "85mm portrait macro lens, shallow depth of field, razor sharp focus on eyes and facial skin",
            "cinematic realism, high fidelity facial pores and micro-textures",
        ]
        return ", ".join(tokens)

    @classmethod
    def synthesize_tier3_action_inpaint_prompt(
        cls,
        name: str,
        action_or_wound: str,
        form_type: str = "STATUS_INJURED",
        char_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """【Tier 3.2: 剧情微距与战损切片 (Inpaint 局部重绘 T2 全身图)】
        以 T2.1 正面全身图为底图，针对手部或特定身体区域重绘战损撕裂或动作。
        """
        if "MACRO" in form_type.upper() or "HAND" in form_type.upper():
            tokens = [
                f"100mm macro photography of {name} hands and gesture",
                f"action details: {action_or_wound}",
                "extreme close-up on hands, fingers and knuckles, visible skin texture, natural hand tension",
                "cinematic rim lighting, shallow depth of field",
            ]
        else:
            tokens = [
                f"cinematic close-up battle damage shot of {name}",
                f"visceral battle damage details: {action_or_wound}",
                "oozing dark red bloodstains, torn fabric edges, frayed cloth texture, realistic skin abrasions and bruises",
                "dramatic chiaroscuro lighting, subtle sweat and wet texture",
            ]
        return ", ".join(tokens)

    @classmethod
    def assemble_character_prompt(
        cls,
        name: str,
        form: str,
        motion_slice: dict[str, Any],
        char_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """按 P0~P4 黄金优先级装配角色生图提示词，深度融合骨相五官、身形骨架、服饰面料与情绪对峙张力。
        【管线调度自适应】：
        - 若属于 T1_BASE / BASE_PORTRAIT，直接调用 synthesize_tier1_face_prompt 实现完全物理隔离；
        - 若属于 4V_FRONT_FULL / BASE_COSTUME，调用 synthesize_tier2_front_prompt 装配全身与 OpenPose 约束；
        - 若属于 4V 衍生视角，调用 synthesize_tier2_view_prompt；
        - 若属于表情重绘，调用 synthesize_tier3_face_inpaint_prompt；
        - 若属于战损或手部特写，调用 synthesize_tier3_action_inpaint_prompt。
        """
        form_upper = form.upper()
        p_face = (
            motion_slice.get("facial_dna_anchor")
            or motion_slice.get("facial_bone_structure")
            or ""
        )
        p_body = (
            motion_slice.get("physique_body_anchor")
            or motion_slice.get("body_proportions")
            or ""
        )
        p_cloth = (
            motion_slice.get("costume_material_anchor")
            or motion_slice.get("costume_and_materials")
            or ""
        )

        # 1. Tier 1 纯面部基准
        # 兼容形态编码多样性 (T1_BASE, BASE_PORTRAIT, 或包含 T1_BASE / BASE_PORTRAIT 的完整资产标识)
        # 注意: 裸 "BASE" 保留给通用基础立绘合成，而 FaceID 纯面部基准必须使用 "T1_BASE" 或 "_T1_BASE"
        is_tier1_face = (
            form_upper in ("T1_BASE", "BASE_PORTRAIT", "PORTRAIT", "MAIN_PORTRAIT", "FACE", "FACE_ID")
            or form_upper.endswith("_T1_BASE")
            or form_upper.endswith("_T1_BASE_PORTRAIT")
            or "_T1_BASE" in form_upper
            or "_BASE_PORTRAIT" in form_upper
        )
        if is_tier1_face:
            logger.debug("【提示词矩阵】角色 [%s] 命中 Tier 1 纯面部基准路由 (form=%s)，执行生物特征纯物理隔离", name, form)
            return cls.synthesize_tier1_face_prompt(
                name=name,
                facial_dna=p_face,
                char_profile=char_profile,
                visual_style=visual_style,
            )

        # 2. Tier 2.1 正面全身图
        if form_upper in ("T1_4V_FRONT_FULL", "4V_FRONT", "4V_FRONT_FULL", "BASE_COSTUME", "COSTUME") or form_upper.endswith("_BASE_COSTUME") or form_upper.endswith("_4V_FRONT"):
            return cls.synthesize_tier2_front_prompt(
                name=name,
                facial_dna=p_face,
                physique_body=p_body,
                costume_material=p_cloth,
                char_profile=char_profile,
                visual_style=visual_style,
            )

        # 3. Tier 2.2 衍生四视角
        if any(v in form_upper for v in ("4V_SIDE", "4V_PROFILE", "4V_BACK", "4V_3Q")):
            return cls.synthesize_tier2_view_prompt(
                name=name,
                view_type=form_upper,
                costume_material=p_cloth,
                char_profile=char_profile,
                visual_style=visual_style,
            )

        # 4. Tier 3.1 微表情重绘
        if "EXP_" in form_upper or "EMOTION" in form_upper:
            expr = (
                motion_slice.get("emotional_expression")
                or motion_slice.get("plot_motion_slice")
                or form
            )
            return cls.synthesize_tier3_face_inpaint_prompt(
                name=name,
                expression_cues=str(expr),
                char_profile=char_profile,
                visual_style=visual_style,
            )

        # 5. Tier 3.2 战损或微距动作切片
        if "INJURED" in form_upper or "MACRO" in form_upper or "HAND" in form_upper:
            wounds = (
                motion_slice.get("physical_wounds")
                or motion_slice.get("plot_motion_slice")
                or motion_slice.get("current_motion")
                or form
            )
            return cls.synthesize_tier3_action_inpaint_prompt(
                name=name,
                action_or_wound=str(wounds),
                form_type=form_upper,
                char_profile=char_profile,
                visual_style=visual_style,
            )

        # 6. 通用兜底装配逻辑 (平滑保底)
        prof = char_profile or {}
        bio = prof.get("biological_dna") or {}
        gender = prof.get("gender") or "person"
        ethnicity_hint = prof.get("ethnicity") or bio.get("ethnicity") or "chinese"
        p0_ethnicity = cls.resolve_ethnicity_token(ethnicity_hint, name)
        facial_bone = p_face or "structured cinematic facial bone structure, natural skin texture"
        p0_slot = f"{p0_ethnicity}, {gender} {name}, Facial & Bone Anatomy: {facial_bone}"
        p1_slot = f"Costume & Fabrics: {p_cloth or 'authentic period weathered fabric, natural tailored folds'}"

        expression = str(motion_slice.get("emotional_expression", "")).strip()
        motion = str(motion_slice.get("current_motion", "")).strip()
        wounds = str(motion_slice.get("physical_wounds", "")).strip()
        tension = str(motion_slice.get("relationship_tension", "")).strip()
        microclimate_rx = str(motion_slice.get("microclimate_reaction", "")).strip()

        dyn_parts: list[str] = []
        if motion:
            dyn_parts.append(f"Action & Posture: {motion}")
        if expression:
            dyn_parts.append(f"Expression: {expression}")
        if tension and tension not in ("无", "none", "中立状态"):
            dyn_parts.append(f"Dramatic Atmosphere & Tension: {tension}")
        if wounds and wounds not in ("无", "none", "null"):
            dyn_parts.append(f"Visceral Battle Wounds: {wounds}, oozing dark red bloodstain, realistic skin abrasion")
        if microclimate_rx and microclimate_rx not in ("无", "none", "null"):
            dyn_parts.append(f"Atmospheric Biometrics: {microclimate_rx}")
        else:
            auto_climate = cls.resolve_microclimate_tokens(f"{motion} {visual_style}")
            if auto_climate:
                dyn_parts.append(f"Atmospheric Biometrics: {auto_climate}")
        p2_slot = ", ".join(dyn_parts)
        # 移除自相矛盾的 "under shoes" 描述，根据是否为半身/全身自适应摄影构图
        p3_slot = "85mm portrait photography, f/1.8 aperture, natural eye-level framing, clean solid neutral studio backdrop"

        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .replace("[placeholder]", "")
            .strip()
        )
        if not clean_style:
            clean_style = "cinematic film lighting, subtle 35mm grain, highly detailed 8k, photorealistic --style raw"
        p4_slot = f"cinematic realism, {cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}"

        tokens = [p0_slot, p1_slot, p2_slot, p3_slot, p4_slot]
        return ", ".join(t for t in tokens if t)

    @classmethod
    def assemble_environment_prompt(
        cls,
        name: str = "",
        form: str = "WIDE",
        env_slice: dict[str, Any] | None = None,
        env_profile: dict[str, Any] | None = None,
        visual_style: str = "",
        **kwargs: Any,
    ) -> str:
        """按四大视听支柱（空间拓扑、光学光位、年代包浆、微气候介质）装配电影工业级场景生图提示词。
        
        支持通过 (name, form, env_slice, ...) 字典插槽组装，也支持直接传入四大支柱命名参数：
        - location / scene_name: 场景名称
        - spatial_topology: 空间拓扑与建筑规制
        - optical_lighting / lighting_rig: 光学光位
        - weathering_patina / period_patina: 年代包浆与地面痕迹
        - micro_climate / atmospheric_medium: 微气候介质
        """
        # 兼容 kwargs 传参
        loc_name = name or kwargs.get("location") or kwargs.get("scene_name") or "cinematic environment"
        slice_data = dict(env_slice or {})
        for k in ("spatial_topology", "optical_lighting", "lighting_rig", "weathering_patina", "period_patina", "micro_climate", "atmospheric_medium", "focal_narrative_spot", "time_weather"):
            if k in kwargs and k not in slice_data:
                slice_data[k] = kwargs[k]

        # 映射别名字段
        if "optical_lighting" in slice_data and "lighting_rig" not in slice_data:
            slice_data["lighting_rig"] = slice_data["optical_lighting"]
        if "weathering_patina" in slice_data and "period_patina" not in slice_data:
            slice_data["period_patina"] = slice_data["weathering_patina"]
        if "micro_climate" in slice_data and "atmospheric_medium" not in slice_data:
            slice_data["atmospheric_medium"] = slice_data["micro_climate"]

        visual_details = str(
            slice_data.get("visual_details")
            or kwargs.get("visual_details")
            or (env_profile.get("visual_details") if env_profile else "")
            or ""
        ).strip()
        if not visual_details:
            raw_vp = str(
                slice_data.get("visual_prompt")
                or (env_profile.get("visual_prompt") if env_profile else "")
                or kwargs.get("visual_prompt")
                or ""
            ).strip()
            if raw_vp and "in the midground:" not in raw_vp and raw_vp != loc_name:
                visual_details = raw_vp

        # Slot 0 & 1 [支柱一：空间拓扑与建筑规制 (Spatial Topology & Architecture)]
        arch_style = (
            slice_data.get("spatial_topology")
            or slice_data.get("architectural_style")
            or (env_profile.get("spatial_topology") if env_profile else "")
            or ""
        )
        ctx_text = f"{arch_style} {slice_data.get('lighting_rig', '')} {slice_data.get('period_patina', '')} {slice_data.get('fixed_set_dressings', '')} {kwargs.get('fixed_set_dressings', '')}"
        period_arch = cls.resolve_period_architecture(visual_style, loc_name, ctx_text)

        # 检查是否挂接五层三维空间蓝图 (Five-Layer Spatial Blueprint)
        bp = (
            slice_data.get("five_layer_blueprint")
            or (env_profile.get("five_layer_blueprint") if env_profile else None)
            or kwargs.get("five_layer_blueprint")
            or kwargs.get("blueprint")
        )

        if not (bp and isinstance(bp, dict)):
            fixed_dressings_candidate = (
                slice_data.get("fixed_set_dressings")
                or (env_profile.get("fixed_set_dressings") if env_profile else None)
                or kwargs.get("fixed_set_dressings")
            )
            if fixed_dressings_candidate:
                bp = {
                    "L1_architecture": arch_style or f"{loc_name} architectural interior frame",
                    "L2_fixed_dressings": fixed_dressings_candidate,
                    "L3_material_patina": slice_data.get("period_patina") or (env_profile.get("period_patina") if env_profile else ""),
                    "L4_optics_microclimate": slice_data.get("atmospheric_medium") or (env_profile.get("atmospheric_medium") if env_profile else ""),
                }
            else:
                try:
                    from app.workflows.nodes.stage6.cinematic_reasoner import CinematicSetDressingReasoner
                    inferred_bp = CinematicSetDressingReasoner.reason_five_layer_blueprint(scene_name=loc_name)
                    if inferred_bp.get("L2_fixed_dressings"):
                        bp = inferred_bp
                except Exception:
                    pass

        if bp and isinstance(bp, dict):
            l1 = arch_style or bp.get("L1_architecture") or f"{loc_name} architectural interior frame"
            l2_raw = bp.get("L2_fixed_dressings") or ""
            l3_raw = slice_data.get("period_patina") or (env_profile.get("period_patina") if env_profile else "") or bp.get("L3_material_patina") or ""

            l4_parts = []
            if slice_data.get("lighting_rig"):
                l4_parts.append(str(slice_data.get("lighting_rig")))
            if slice_data.get("atmospheric_medium"):
                l4_parts.append(str(slice_data.get("atmospheric_medium")))
            if not l4_parts and bp.get("L4_optics_microclimate"):
                l4_parts.append(str(bp.get("L4_optics_microclimate")))
            l4_raw = "，".join(l4_parts)

            dressings: list[str] = []
            if isinstance(l2_raw, list):
                dressings = [str(d).strip() for d in l2_raw if str(d).strip()]
            elif isinstance(l2_raw, str):
                dressings = [d.strip() for d in re.split(r"[；;，,]", l2_raw) if d.strip()]

            fg_items: list[str] = []
            mg_items: list[str] = []
            bg_items: list[str] = []

            for d in dressings:
                if any(k in d for k in ("火盆", "地面", "地砖", "阶前", "台前", "散落", "门槛", "前", "纸灰", "灰烬", "floor")):
                    fg_items.append(d)
                elif any(k in d for k in ("幡", "联", "梁", "窗", "门", "墙", "栏杆", "管道", "立柱", "大门", "窗格", "远", "wall", "ceiling")):
                    bg_items.append(d)
                else:
                    mg_items.append(d)

            bg_items.insert(0, l1)

            spatial_layers = []
            if fg_items:
                spatial_layers.append(f"in the foreground: {', '.join(fg_items)}")
            if mg_items:
                spatial_layers.append(f"in the midground: {', '.join(mg_items)}")
            if bg_items:
                spatial_layers.append(f"in the background: {', '.join(bg_items)}")

            p0_slot = f"{period_arch}, spatial location: {loc_name}, Three-Dimensional Spatial Blueprint: {'; '.join(spatial_layers)}"

            p2_dyn = []
            if l3_raw:
                p2_dyn.append(f"Period Patina & Surface Wear: {l3_raw}")
            if l4_raw:
                p2_dyn.append(f"Lighting & Atmospheric Microclimate: {l4_raw}")
            if visual_details:
                p2_dyn.append(f"Visual Narrative Details: {visual_details}")
            climate_particles = cls.resolve_microclimate_tokens(f"{loc_name} {l4_raw} {l3_raw} {visual_style}")
            if climate_particles:
                p2_dyn.append(f"Atmospheric Media: {climate_particles}")
            p2_slot = ", ".join(p2_dyn) if p2_dyn else ""
        elif arch_style:
            p0_slot = f"{period_arch}, spatial location: {loc_name}, Spatial Topology & Architecture: {arch_style}"
        else:
            p0_slot = f"{period_arch}, spatial location: {loc_name}"

        # Slot 2 [支柱二：光学光位 (Lighting Rig) + 支柱三：年代包浆 (Period Patina) + 支柱四：微气候介质 (Atmospheric Medium)]
        if not (bp and isinstance(bp, dict)):
            sub_spot = str(slice_data.get("focal_narrative_spot") or slice_data.get("sub_zone_spot", "")).strip()
            lighting = str(
                slice_data.get("lighting_rig")
                or slice_data.get("lighting_and_atmosphere")
                or (env_profile.get("lighting_rig") if env_profile else "")
                or ""
            ).strip()
            traces = str(
                slice_data.get("period_patina")
                or slice_data.get("scene_traces")
                or (env_profile.get("period_patina") if env_profile else "")
                or ""
            ).strip()
            atm_medium = str(
                slice_data.get("atmospheric_medium")
                or (env_profile.get("atmospheric_medium") if env_profile else "")
                or ""
            ).strip()

            dyn_parts: list[str] = []
            if sub_spot and sub_spot not in ("无", "none", "全景"):
                dyn_parts.append(f"focal camera zone: {sub_spot}")
            if lighting and lighting not in ("无", "none"):
                dyn_parts.append(f"Lighting Rig: {lighting}")
            if traces and traces not in ("无", "none"):
                dyn_parts.append(f"Period Patina & Ground Traces: {traces}")
            if atm_medium and atm_medium not in ("无", "none"):
                dyn_parts.append(f"Atmospheric Medium: {atm_medium}")
            else:
                # 微环境悬浮微粒（丁达尔尘埃/香烛烟雾等）自动补齐
                climate_particles = cls.resolve_microclimate_tokens(f"{loc_name} {traces} {lighting} {visual_style}")
                if climate_particles:
                    dyn_parts.append(f"atmospheric media: {climate_particles}")
            if visual_details:
                dyn_parts.append(f"Visual Narrative Details: {visual_details}")
            p2_slot = ", ".join(dyn_parts)

        # Slot 3 [P3: 光学焦段与景深]
        if "ZONE" in form.upper():
            p3_slot = "50mm medium lens, atmospheric perspective, focused framing on interior zone with tangible spatial depth"
        elif bp and isinstance(bp, dict):
            p3_slot = "28mm wide-angle establish shot, deep focus, grand architectural interior perspective, expansive field of view"
        else:
            p3_slot = "35mm cinematic anamorphic lens, established wide angle shot, grand environmental perspective, deep depth of field"

        # Slot 4 [P4: 真实影调展开与电影光学瑕疵]
        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .strip()
            or "cinematic atmospheric lighting, realistic volumetric haze, 8k --style raw"
        )
        p4_slot = f"master cinematic lighting, zero humans, empty scene, {cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}"

        tokens = [p0_slot, p2_slot, p3_slot, p4_slot]
        return ", ".join(t for t in tokens if t)

    @classmethod
    def assemble_prop_prompt(
        cls,
        name: str,
        form: str,
        prop_slice: dict[str, Any],
        prop_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """按纯净物性标准装配道具生图提示词，严禁生物特征污染，融合材质工艺、承载底座与战损做旧。"""
        prof = prop_profile or {}

        # ---------------------------------------------------------------------
        # 0. 特殊画中人/遗像物证卡专有组装逻辑 (Special Portrait Decoupled Prop)
        # ---------------------------------------------------------------------
        is_portrait = (
            bool(prop_slice.get("is_portrait_element"))
            or bool(prof.get("is_portrait_element"))
            or any(k in name for k in ("遗像", "遗照", "相框肖像", "FUNERAL_PORTRAIT"))
        )
        if is_portrait:
            target_char = str(
                prop_slice.get("target_character")
                or prof.get("target_character")
                or ""
            ).strip()
            if not target_char:
                m = re.search(r"([\u4e00-\u9fa5]{2,4})(?:黑白)?(?:遗像|遗照|相框)", name)
                if m:
                    target_char = m.group(1)
            char_title = target_char or name
            clean_style = (
                visual_style.replace("[visual_style]", "")
                .replace("visual style:", "")
                .strip()
                or "cinematic studio lighting, 8k resolution, photorealistic masterpiece"
            )
            return (
                f"Authentic framed monochrome black and white funeral tribute portrait of {char_title}, "
                f"dignified frontal close-up angle, somber and solemn expression, "
                f"framed in a dark lacquered solid wood picture frame with a neat black silk mourning ribbon (挽黑纱实木相框), "
                f"faint reflections on clean glass surface, neutral dark studio photography backdrop, "
                f"soft rim lighting, {clean_style} --style raw"
            )

        # Slot 0 [P0: 纯净物理实体、材质规格与工艺纹理]
        material = (
            prop_slice.get("material_specs")
            or prop_slice.get("material_details")
            or prof.get("material_specs")
            or prof.get("material")
            or "aged antique crafted metal, tactile physical texture"
        )
        craft = (
            prop_slice.get("craft_texture")
            or prof.get("craft_texture")
            or ""
        )
        craft_str = f", Craft & Texture: {craft}" if craft else ""
        p0_slot = f"Authentic tactile hero prop: {name}, Material Specs: {material}{craft_str}"

        # Slot 1 [P1: 承载底座接地介质与无缝摄影棚背景 (杜绝场景背景混入)]
        surface = str(
            prop_slice.get("resting_surface")
            or prop_slice.get("placement_surface", "")
            or prof.get("resting_surface", "")
        ).strip()
        if not surface or surface in ("无", "none"):
            surface = "resting firmly on weathered dark textured wooden tabletop"
        p1_slot = f"isolated hero prop studio shot, grounded physical contact: {surface}, neutral dark gray seamless backdrop, soft contact occlusion shadow"

        # Slot 2 [P2: 剧情破坏形态、碎裂特征与岁月包浆程度]
        damage = str(
            prop_slice.get("physical_damage_desc")
            or prop_slice.get("damage_state", "")
        ).strip()
        fracture = str(prop_slice.get("fracture_characteristics") or "").strip()
        wear = str(
            prop_slice.get("patina_degree")
            or prop_slice.get("wear_and_tear", "")
            or prof.get("patina_degree", "")
        ).strip()

        dyn_prop_states: list[str] = []
        is_damaged = (
            "ACTION" in form.upper()
            or damage.upper() in ("DAMAGED", "BROKEN")
            or (damage and damage not in ("无", "none", "初始完整形态"))
        )
        if is_damaged:
            frac_str = f", fracture details: {fracture}" if fracture else ""
            dyn_prop_states.append(f"state: narrative battle damaged state, {damage or 'visible fractures, edge chipping'}{frac_str}")
        else:
            dyn_prop_states.append("state: pristine intact condition, natural tactile patina, realistic subtle edge wear")
        if wear and wear not in ("无", "none", "null"):
            dyn_prop_states.append(f"patina & erosion: {wear}")
        p2_slot = ", ".join(dyn_prop_states)

        # Slot 3 [P3: 100mm 极端微距摄影]
        p3_slot = "100mm macro lens photography, razor-sharp focus on fine engraving and material grain, shallow depth of field, sharp focus on hero prop"

        # Slot 4 [P4: 风格化渲染与电影光学微瑕疵]
        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .strip()
            or "cinematic studio lighting, soft diffused highlights, photorealistic 8k --style raw"
        )
        p4_slot = f"{cls.CINEMATIC_OPTICAL_DIRECTIVES}, soft three-point studio lighting, {clean_style}"

        tokens = [p0_slot, p1_slot, p2_slot, p3_slot, p4_slot]
        return ", ".join(t for t in tokens if t)

    @classmethod
    def assemble_character_t1_base_prompt(
        cls, name: str, facial_bone: str, costume_materials: str, style: str = ""
    ) -> str:
        """组装角色 T1 基准立绘正向生图提示词。"""
        clean_style = style.replace("[visual_style]", "").strip() or "cinematic realism, 8k"
        return (
            f"masterpiece cinematic character sheet, wide angle full-length shot, "
            f"complete body from top of head to soles of shoes, grounded shadows on floor, "
            f"clean solid neutral dark gray studio photography backdrop, neutral studio lighting. "
            f"Character: {name}. "
            f"Facial & Bone Structure: {facial_bone}. "
            f"Costume & Fabrics: {costume_materials}. "
            f"8k resolution, cinematic composition, hyper-realistic skin texture, realistic fabric draping, "
            f"sharp focus, shot on 35mm lens, {clean_style}."
        )

    @classmethod
    def assemble_character_t3_injured_prompt(
        cls,
        name: str,
        facial_bone: str,
        wounds: str,
        costume_materials: str,
        expression: str = "",
        tension: str = "",
        style: str = "",
    ) -> str:
        """组装角色 T3 战伤负伤态图生图/文生图提示词。"""
        clean_style = style.replace("[visual_style]", "").strip() or "cinematic realism, 8k"
        return (
            f"cinematic medium shot of {name}, intense dramatic battle aftermath, "
            f"Physical Injuries & Wounds: {wounds}, visceral realistic blood stains soaking into torn fabric. "
            f"Facial Bone & Eyes: {facial_bone}, Facial Expression: {expression or 'intense painful grimace'}. "
            f"Emotional Atmosphere & Dynamic Tension: {tension or 'tense survival struggle'}. "
            f"Costume Battle Distress: {costume_materials}, distressed textures, grime, sweat. "
            f"Dramatic rim lighting, dark moody contrast, volumetrics, hyper-detailed skin pores and coagulated blood, "
            f"shallow depth of field, 8k resolution, {clean_style}."
        )

    @classmethod
    def compile_scene_master_prompt(
        cls,
        scene_name: str,
        blueprint: dict[str, Any] | None = None,
        view_type: str = "WIDE",
        visual_style: str = "",
        **kwargs: Any,
    ) -> SynthesizedPrompt:
        """根据五层视听空间蓝图，编译包含三维方位介词的 Master Prompt。

        【空间拓扑三维锚定铁律】：
        - in the foreground: 近处地面支撑面与低矮陈设（火盆、供桌前端、掉落纸灰香灰）
        - in the midground: 核心承载面与主体固定陈设（正中实木供桌、棺木、挽黑纱实木相框环境态）
        - in the background: 空间挑高与纵深远景（木梁、通风格栅、悬挂白色祭幡与挽联）
        - Material Patina: L3 表面年代包浆与地面痕迹
        - Lighting & Microclimate: L4 穿堂冷风、烛光跳跃与青白烟雾
        - 摄影机镜头指令: 28mm wide-angle establish shot, deep focus, grand architectural geometry
        - 纯净空镜排斥: 强制注入 negative_prompt 并显式要求 zero humans, nobody
        """
        bp = blueprint or kwargs.get("five_layer_blueprint") or {}
        l1 = bp.get("L1_architecture") or f"{scene_name} architectural interior frame"
        l2_raw = bp.get("L2_fixed_dressings") or ""
        l3_raw = bp.get("L3_material_patina") or ""
        l4_raw = bp.get("L4_optics_microclimate") or ""

        dressings: list[str] = []
        if isinstance(l2_raw, list):
            dressings = [str(d).strip() for d in l2_raw if str(d).strip()]
        elif isinstance(l2_raw, str):
            dressings = [d.strip() for d in re.split(r"[；;，,]", l2_raw) if d.strip()]

        extra_dressings = kwargs.get("fixed_dressings") or kwargs.get("fixed_set_dressings") or []
        if isinstance(extra_dressings, list):
            for ed in extra_dressings:
                ed_str = str(ed).strip()
                if ed_str and ed_str not in dressings:
                    dressings.append(ed_str)

        fg_items: list[str] = []
        mg_items: list[str] = []
        bg_items: list[str] = []

        for d in dressings:
            if any(k in d for k in ("火盆", "地面", "地砖", "阶前", "台前", "散落", "门槛", "脚边", "地")):
                fg_items.append(d)
            elif any(k in d for k in ("幡", "联", "梁", "窗", "门", "墙", "栏杆", "管道", "远", "排风")):
                bg_items.append(d)
            else:
                mg_items.append(d)

        bg_items.insert(0, l1)

        spatial_tokens: list[str] = []
        if fg_items:
            spatial_tokens.append(f"in the foreground: {', '.join(fg_items)}")
        if mg_items:
            spatial_tokens.append(f"in the midground: {', '.join(mg_items)}")
        if bg_items:
            spatial_tokens.append(f"in the background: {', '.join(bg_items)}")

        atmosphere_tokens: list[str] = []
        if l3_raw:
            atmosphere_tokens.append(f"Material Patina & Surface Wear: {l3_raw}")
        if l4_raw:
            atmosphere_tokens.append(f"Lighting & Atmospheric Microclimate: {l4_raw}")

        vt = view_type.strip().upper()
        if vt in ("WIDE", "MASTER", "ESTABLISH", "T1_WIDE"):
            camera_directive = "28mm wide-angle establish shot, deep focus, grand architectural interior perspective, expansive field of view"
        elif vt in ("ZONE", "Z01", "MEDIUM"):
            camera_directive = "50mm medium cinematic framing, atmospheric perspective on localized interior zone"
        else:
            camera_directive = "35mm cinematic lens, balanced composition"

        effective_style = visual_style or str(kwargs.get("style") or "")
        clean_style = (
            effective_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .strip()
            or "cinematic dramatic lighting, atmospheric volumetrics, photorealistic 8k --style raw"
        )

        all_parts = [
            f"masterpiece empty cinematic environment of {scene_name}",
            camera_directive,
            "; ".join(spatial_tokens),
            "; ".join(atmosphere_tokens),
            "deserted scene, zero humans, nobody, completely unoccupied",
            clean_style,
        ]
        composed_visual_prompt = ", ".join(p for p in all_parts if p)
        delta_prompt = "; ".join(spatial_tokens + atmosphere_tokens)
        negative_prompt = PromptSynthesizer.get_negative_prompt("environment")
        return SynthesizedPrompt(
            delta_prompt=delta_prompt,
            visual_prompt=composed_visual_prompt,
            identity_prompt=l1,
            negative_prompt=negative_prompt,
        )

    @classmethod
    def assemble_scene_wide_prompt(
        cls, scene_name: str, architectural_style: str, lighting_atmosphere: str, scene_traces: str, style: str = ""
    ) -> str:
        """组装场景 T1 全景空镜生图提示词。"""
        clean_style = style.replace("[visual_style]", "").strip() or "cinematic atmospheric lighting, 8k"
        return (
            f"masterpiece cinematic wide empty environment shot of {scene_name}, "
            f"Architectural Structure & Materials: {architectural_style}. "
            f"Lighting & Atmospheric Mood: {lighting_atmosphere}. "
            f"Environmental Traces & Ground Details: {scene_traces}. "
            f"Extreme depth of field, panoramic cinematic framing, volumetric lighting, photorealistic textures, "
            f"shot on 24mm anamorphic lens, 8k resolution, {clean_style}."
        )

    @classmethod
    def assemble_scene_zone_prompt(
        cls, scene_name: str, sub_zone_spot: str, lighting_atmosphere: str, scene_traces: str, style: str = ""
    ) -> str:
        """组装场景 Z01 局部子机位生图提示词。"""
        clean_style = style.replace("[visual_style]", "").strip() or "cinematic lighting, 8k"
        return (
            f"cinematic medium interior zone shot, focusing on {sub_zone_spot} within {scene_name}. "
            f"Atmospheric Lighting: {lighting_atmosphere}. "
            f"Intimate Space Details & Traces: {scene_traces}. "
            f"Atmospheric dust motes, tactile wood and metal surfaces, subtle shadow falloff, "
            f"8k resolution, photojournalistic realism, {clean_style}."
        )


# 将 PromptMatrixSynthesizer 的核心装配能力注入 PromptSynthesizer，形成统一门面接口
PromptSynthesizer.assemble_environment_prompt = PromptMatrixSynthesizer.assemble_environment_prompt
PromptSynthesizer.assemble_prop_prompt = PromptMatrixSynthesizer.assemble_prop_prompt
PromptSynthesizer.assemble_character_prompt = PromptMatrixSynthesizer.assemble_character_prompt
PromptSynthesizer.assemble_character_t1_base_prompt = PromptMatrixSynthesizer.assemble_character_t1_base_prompt
PromptSynthesizer.assemble_character_t3_injured_prompt = PromptMatrixSynthesizer.assemble_character_t3_injured_prompt
PromptSynthesizer.assemble_scene_wide_prompt = PromptMatrixSynthesizer.assemble_scene_wide_prompt
PromptSynthesizer.assemble_scene_zone_prompt = PromptMatrixSynthesizer.assemble_scene_zone_prompt
PromptSynthesizer.compile_scene_master_prompt = PromptMatrixSynthesizer.compile_scene_master_prompt
PromptSynthesizer.ContinuityStateManager = ContinuityStateManager
PromptSynthesizer.PhysicalEntityState = PhysicalEntityState


