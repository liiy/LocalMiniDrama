"""全剧资产四维提示词解耦与视觉/声学提示词合成器 (PromptSynthesizer)。

【提示词四维解耦架构】：
1. identity_prompt: 生物人脸与本体特征基准锚点（仅五官、发型、骨相、生物DNA，剥离服饰、姿态与情绪）。
2. delta_prompt: 视角、机位、定妆、表情、光影增量修饰词。
3. composed_visual_prompt / image_prompt: 物理执行的完整视听正向提示词 (identity + delta + style)。
4. negative_prompt: 分资产大类的工业级通用与专属排斥词。
"""
from __future__ import annotations

import re
from typing import Any, Mapping, NamedTuple


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
        "plastic skin, oversaturated, deformed face, asymmetrical eyes, missing teeth, extra teeth, "
        "unrealistic hair, extra limbs, anime render, 3d render, doll-like, airbrushed, cartoon, "
        "low polygon, smooth porcelain skin, distorted iris, cross-eyed, deformed mouth, extra digits, "
        "turnaround sheet, character sheet, multiple views, multiple angles, split screen, 4-grid, 3-view, "
        "collage, diptych, triptych, reference sheet, multiple people, two persons, crowd, group of people"
    ),
    "SCENE_NEGATIVE": (
        "indoor clutter, modern elements in ancient scene, floating furniture, warped perspective, "
        "crooked architecture, unnatural lighting, artifacts, CGI look, blurry background, low-res texture, "
        "watermark, signature, text, oversaturated lighting, distorted walls"
    ),
    "PROP_NEGATIVE": (
        "deformed object, unrealistic proportions, floating parts, inconsistent texture, melted look, "
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

        if vt in ("BASE_PORTRAIT", "PORTRAIT", "MAIN_PORTRAIT"):
            delta_parts.append(
                "single person, neutral frontal headshot portrait, 85mm portrait lens, eye-level angle, neutral resting facial expression, shallow depth of field, sharp focus on eyes, soft rim lighting"
            )
        elif vt in ("BASE_COSTUME", "COSTUME", "FULL_BODY", "FULLBODY"):
            costume_desc = costume_prompt or "tailored character outfit, realistic textured fabric folds"
            delta_parts.append(
                f"single person, standing full body establishing shot, eye-level framing, wearing {costume_desc}, natural relaxed posture, neutral facial expression, realistic fabric drape and creases, head-to-toe framing"
            )
        elif vt in ("4V_FRONT", "FRONT", "FRONT_VIEW"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, full body front view portrait, neutral A-pose, facing camera directly, centered composition, wearing {costume_desc}, clean solid neutral studio backdrop, flat even studio reference lighting, ortho camera perspective, symmetry, isolated figure, full body head-to-toe"
            )
        elif vt in ("4V_SIDE", "SIDE", "SIDE_VIEW", "PROFILE", "4V_PROFILE"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, full body exact 90-degree side profile view, neutral A-pose, facing sideways, wearing {costume_desc}, clean solid neutral studio backdrop, flat even studio reference lighting, ortho camera perspective, isolated figure, full body head-to-toe"
            )
        elif vt in ("4V_BACK", "BACK", "BACK_VIEW", "REAR"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, full body 180-degree rear back view showing back details, neutral A-pose, facing away from camera, wearing {costume_desc}, clean solid neutral studio backdrop, flat even studio reference lighting, ortho camera perspective, isolated figure, full body head-to-toe"
            )
        elif vt in ("4V_THREE_QUARTER", "THREE_QUARTER", "THREE_QUARTER_VIEW", "4V_3Q", "3Q"):
            costume_desc = costume_prompt or "standard character outfit"
            delta_parts.append(
                f"single person, full body 45-degree three-quarter view, neutral A-pose, turned at three-quarter angle, wearing {costume_desc}, clean solid neutral studio backdrop, flat even studio reference lighting, ortho camera perspective, isolated figure, full body head-to-toe"
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
                "isolated hero prop studio shot, 100mm macro lens, pristine condition, centered composition, soft three-point product lighting, neutral dark gray backdrop, sharp focus on surface material"
            )
        elif vt in ("ACTION", "INTERACTION"):
            s_desc = state_prompt or "functional interaction state"
            delta_parts.append(
                f"dynamic hand-held prop in narrative action, {s_desc}, active character hand interaction, motion context, shallow depth of field, dramatic cinematic side light"
            )
        elif vt in ("DETAIL", "MACRO"):
            s_desc = f", {state_prompt}" if state_prompt else ""
            delta_parts.append(
                f"extreme macro texture shot, tactile material fissures, mechanical engravings, microscopic wear and tear, micro depth of field{s_desc}"
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

        if vt in ("STATIC", "PRISTINE"):
            delta_parts.append(
                "isolated hero prop shot, centered composition, pristine original condition, intact physical structure, soft studio product lighting, ultra-sharp texture details"
            )
        elif vt.startswith("ACTION") or vt in ("DAMAGED", "BURNT"):
            st = state_prompt or "damaged condition, physical wear and tear, scorch marks or cracks"
            delta_parts.append(
                f"prop in damaged interactive state, {st}, realistic physical destruction, broken fragments, scorched surface, high-contrast gritty lighting"
            )
        elif vt in ("DETAIL", "MACRO"):
            delta_parts.append(
                "extreme macro detail shot, 100mm macro lens, ultra-shallow depth of field, tactile material texture, mechanical joints and engraved markings, intimate craftsmanship"
            )
        else:
            delta_parts.append(f"prop view {view_type}, {state_prompt}")

        delta_prompt = "; ".join(delta_parts)
        base = base_prop_prompt or "tactile hero prop item"
        composed = (
            f"cinematic photorealistic 8k hero prop photography, {base}, {delta_prompt}, "
            f"visual style: {visual_style} --style raw"
        )
        return delta_prompt, composed
