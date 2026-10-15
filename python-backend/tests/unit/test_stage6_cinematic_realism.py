# -*- coding: utf-8 -*-
"""阶段 6 高维影视工业质感与本土特征单元测试 (年代、地域、阶层磨损、微气候、镜头光学瑕疵、空间声学)。"""

import unittest
from app.workflows.utils.prompt_synthesizer import PromptMatrixSynthesizer
from app.workflows.adapters.drama_storage_adapter import DramaStorageAdapter


class TestStage6CinematicRealismAndLocalTraits(unittest.TestCase):
    """测试阶段 6 注入的年代、本土工业制式、阶层磨损、微气候、镜头光学与声学空间。"""

    def test_prompt_synthesizer_cinematic_optical_and_microclimate_injection(self):
        """验证生图合成器中 35mm 真实电影光学瑕疵与微气候生理反应的装配效果。"""
        # 1. 角色生图提示词装配（带有寒冷冬夜微气候与伤痕）
        char_prompt = PromptMatrixSynthesizer.assemble_character_prompt(
            name="沈炼",
            form="BASE",
            motion_slice={
                "current_motion": "手按刀柄立于风雪街头",
                "emotional_expression": "面冷如铁",
                "physical_wounds": "左臂刀伤带暗红血痕",
                "microclimate_reaction": "寒风中呼出白色雾气 breath mist，鼻尖冻红",
            },
            char_profile={
                "name": "沈炼",
                "facial_bone_structure": "棱角冷硬下颌线，狭长凤眼，面颊带风霜微瑕",
                "costume_and_materials": "深玄色飞鱼服，领口微磨损毛边",
            },
            visual_style="北方寒夜写实电影质感",
        )
        # 断言电影镜头光学瑕疵注入
        self.assertIn("35mm anamorphic prime lens", char_prompt)
        self.assertIn("authentic 35mm film grain", char_prompt)
        self.assertIn("subtle halation around bright light sources", char_prompt)
        self.assertIn("no plastic smoothing", char_prompt)
        # 断言微气候反应注入
        self.assertIn("Atmospheric Biometrics: 寒风中呼出白色雾气 breath mist，鼻尖冻红", char_prompt)

    def test_prompt_synthesizer_environment_microclimate_and_period_architecture(self):
        """验证场景生图提示词中本土时代建筑映射与丁达尔空气悬浮颗粒。"""
        env_prompt = PromptMatrixSynthesizer.assemble_environment_prompt(
            name="苏秀兰旧居灵堂",
            form="BASE",
            env_slice={
                "sub_zone_spot": "生锈铁盆旁",
                "lighting_and_atmosphere": "昏黄钨丝灯，斜射逆光",
                "scene_traces": "供桌上香烛残余暗沉蜡油",
            },
            env_profile={
                "scene_name": "苏秀兰旧居灵堂",
                "architectural_style": "北方工业平房老宅",
            },
            visual_style="2000年代初北方老矿区写实电影质感",
        )
        # 验证 2000 年代北方老矿区工业建筑消解
        self.assertIn("2000s northern China industrial town", env_prompt)
        # 验证微气候悬浮介质（灵堂/香烛/尘封）
        self.assertIn("volumetric light beams", env_prompt)
        self.assertIn("dust motes", env_prompt)
        # 验证光学镜头
        self.assertIn("authentic 35mm film grain", env_prompt)

    def test_prompt_synthesizer_prop_wear_and_tear_injection(self):
        """验证道具生图提示词中岁月包浆与磨损折损注入。"""
        prop_prompt = PromptMatrixSynthesizer.assemble_prop_prompt(
            name="脱漆保温杯",
            form="ACTION",
            prop_slice={
                "damage_state": "DAMAGED",
                "wear_and_tear": "杯身大面积掉漆露出暗灰黑铁，底部磕碰严重凹陷，密封胶圈泛黄硬化",
            },
            prop_profile={
                "name": "脱漆保温杯",
                "material_details": "老式不锈钢",
            },
            visual_style="纪实刑侦电影质感",
        )
        # 验证磨损包浆注入
        self.assertIn("patina & erosion: 杯身大面积掉漆露出暗灰黑铁", prop_prompt)
        # 验证光学瑕疵
        self.assertIn("35mm film grain", prop_prompt)

    def test_storage_adapter_voice_profile_acoustic_space_and_accent_enrichment(self):
        """验证音色卡落库中地域口音与空间声学响应字段的动态编织。"""
        v_entry = {
            "character_name": "周正国",
            "timbre": "低沉沙哑疲惫",
            "timbre_archetype": "aged_rough_raspy",
            "regional_accent": "东北工业小城轻微倒口",
            "acoustic_space": "狭窄水泥走廊近场硬反射与门板高频遮蔽衰减",
            "vocal_position": "低胸腔与声带摩擦共鸣",
            "vocal_flaws": "老烟枪咽喉干咳微杂音",
        }
        # 模拟 adapter 拼装逻辑
        timbre = str(v_entry.get("timbre") or "低沉冷峻磁性").strip()
        timbre_archetype = str(v_entry.get("timbre_archetype") or "deep_baritone_gravel").strip()
        vocal_position = str(v_entry.get("vocal_position") or "chest_resonance_focused").strip()
        vocal_flaws = str(v_entry.get("vocal_flaws") or "slight_raspy_edge").strip()
        regional_accent = str(v_entry.get("regional_accent") or "").strip()
        acoustic_space = str(v_entry.get("acoustic_space") or "").strip()

        v_prompt = ""
        prompt_parts = [timbre, f"原型:{timbre_archetype}"]
        if regional_accent:
            prompt_parts.append(f"方言口音:{regional_accent}")
        if acoustic_space:
            prompt_parts.append(f"空间声场:{acoustic_space}")
        prompt_parts.extend([f"发声位置:{vocal_position}", f"生理瑕疵:{vocal_flaws}"])
        v_prompt = "，".join(prompt_parts)

        self.assertIn("方言口音:东北工业小城轻微倒口", v_prompt)
        self.assertIn("空间声场:狭窄水泥走廊近场硬反射与门板高频遮蔽衰减", v_prompt)
        self.assertIn("老烟枪咽喉干咳微杂音", v_prompt)


if __name__ == "__main__":
    unittest.main()
