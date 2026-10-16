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
        if isinstance(prop_or_prompt, str):
            base_prop_prompt = prop_or_prompt
        elif isinstance(prop_or_prompt, dict):
            base_prop_prompt = str(prop_or_prompt.get("visual_prompt") or prop_or_prompt.get("prompt") or prop_or_prompt.get("name") or "")
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
                f"extreme macro texture shot, resting firmly on physical surface, tactile material fissures, mechanical engravings, microscopic wear and tear, micro depth of field{s_desc}"
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
    def resolve_period_architecture(cls, visual_style: str = "", env_name: str = "") -> str:
        """从全剧视觉风格或场景名中消解出具象时代建筑材质与本土特征。"""
        combined = f"{visual_style} {env_name}".lower()
        if any(kw in combined for kw in ("80", "八十", "筒子楼", "红砖", "厂区", "国企", "老工")):
            return cls.PERIOD_ARCHITECTURE_MAP["1980s_china"]
        elif any(kw in combined for kw in ("90", "九十", "防盗网", "马赛克")):
            return cls.PERIOD_ARCHITECTURE_MAP["1990s_china"]
        elif any(kw in combined for kw in ("2000", "00", "老矿", "老宅", "旧居", "灵堂", "平房", "北方", "工业镇")):
            return cls.PERIOD_ARCHITECTURE_MAP["2000s_industrial_china"]
        elif any(kw in combined for kw in ("江南", "水乡", "青瓦", "粉墙", "乌镇")):
            return cls.PERIOD_ARCHITECTURE_MAP["jiangnan_water_town"]
        elif any(kw in combined for kw in ("明", "武侠", "古装", "客栈", "破庙", "江湖")):
            return cls.PERIOD_ARCHITECTURE_MAP["ming_wuxia"]
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
            view_desc = "full length three-quarter 45-degree angle view portrait, standing dynamic stance, showing costume depth"
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
        name: str,
        form: str,
        env_slice: dict[str, Any],
        env_profile: dict[str, Any] | None = None,
        visual_style: str = "",
    ) -> str:
        """按 P0~P4 黄金优先级装配场景生图提示词，深度融合建筑规制、光影氛围与空间痕迹。"""
        # Slot 0 & 1 [P0+P1: 具象时代空间世界观建筑材质]
        period_arch = cls.resolve_period_architecture(visual_style, name)
        arch_style = env_slice.get("architectural_style")
        if arch_style:
            p0_slot = f"{period_arch}, spatial location: {name}, Architecture & Spatial Structure: {arch_style}"
        else:
            p0_slot = f"{period_arch}, spatial location: {name}"

        # Slot 2 [P2: 当集子机位、空间光影与剧情物理残留痕迹 + 微气候悬浮介质]
        sub_spot = str(env_slice.get("sub_zone_spot", "")).strip()
        traces = str(env_slice.get("scene_traces", "")).strip()
        lighting = str(env_slice.get("lighting_and_atmosphere", "")).strip()

        dyn_parts: list[str] = []
        if sub_spot and sub_spot not in ("无", "none", "全景"):
            dyn_parts.append(f"specific focal camera zone: {sub_spot}")
        if lighting and lighting not in ("无", "none"):
            dyn_parts.append(f"Lighting & Atmosphere: {lighting}")
        if traces and traces not in ("无", "none"):
            dyn_parts.append(f"narrative environmental traces: {traces}")
        # 微环境悬浮微粒（丁达尔尘埃/香烛烟雾）
        climate_particles = cls.resolve_microclimate_tokens(f"{name} {traces} {lighting} {visual_style}")
        if climate_particles:
            dyn_parts.append(f"atmospheric media: {climate_particles}")
        p2_slot = ", ".join(dyn_parts)

        # Slot 3 [P3: 光学焦段与景深]
        if "ZONE" in form.upper():
            p3_slot = "50mm medium lens, atmospheric perspective, focused framing on interior zone with tangible spatial depth"
        else:
            p3_slot = "35mm cinematic anamorphic lens, established wide angle shot, grand environmental perspective, deep depth of field"

        # Slot 4 [P4: 真实影调展开与电影光学瑕疵]
        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .strip()
            or "cinematic atmospheric lighting, realistic volumetric haze, 8k --style raw"
        )
        p4_slot = f"master cinematic lighting, {cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}"

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
        """按 P0~P4 黄金优先级装配道具生图提示词，深度融合微观材质纹理与放置接触面。"""
        # Slot 0 [P0: 道具核心实体与材质细节]
        prof = prop_profile or {}
        material = (
            prop_slice.get("material_details")
            or prof.get("material")
            or "aged antique crafted metal, tactile physical texture"
        )
        p0_slot = f"Authentic tactile hero prop: {name}, Material & Micro Texture: {material}"

        # Slot 1 [P1: 承载底座接地介质 (拒绝悬浮)]
        surface = str(prop_slice.get("placement_surface", "")).strip()
        if not surface or surface in ("无", "none"):
            surface = "resting firmly on weathered dark textured wooden tabletop"
        p1_slot = f"grounded physical contact: {surface}, soft contact occlusion shadow"

        # Slot 2 [P2: 剧情破坏/交互物理状态与岁月包浆磨损]
        damage = str(prop_slice.get("damage_state", "")).strip()
        wear = str(prop_slice.get("wear_and_tear", "")).strip()
        dyn_prop_states: list[str] = []
        if "ACTION" in form.upper() or damage.upper() in ("DAMAGED", "BROKEN"):
            dyn_prop_states.append("state: damaged action state, visible fractures, edge chipping, surface scratch abrasions")
        else:
            dyn_prop_states.append("state: pristine intact condition, natural tactile patina, realistic subtle edge wear")
        if wear and wear not in ("无", "none", "null"):
            dyn_prop_states.append(f"patina & erosion: {wear}")
        p2_slot = ", ".join(dyn_prop_states)

        # Slot 3 [P3: 100mm 极端微距摄影]
        p3_slot = "100mm macro lens photography, razor-sharp focus on fine engraving and material grain, shallow depth of field"

        # Slot 4 [P4: 风格化渲染与电影光学微瑕疵]
        clean_style = (
            visual_style.replace("[visual_style]", "")
            .replace("visual style:", "")
            .strip()
            or "cinematic studio lighting, soft diffused highlights, photorealistic 8k --style raw"
        )
        p4_slot = f"{cls.CINEMATIC_OPTICAL_DIRECTIVES}, {clean_style}"

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

