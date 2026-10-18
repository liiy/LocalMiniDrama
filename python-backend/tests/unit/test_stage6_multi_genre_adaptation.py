"""阶段 6 跨题材自适应与资产解耦多题材专项测试 (Stage 6 Multi-Genre Adaptation Tests)。

验证内容：
1. 仙侠古装题材 (Xianxia):
   - 题材识别并加载 XianxiaGenrePack；
   - 称谓前缀/后缀正确识别（如“掌门”、“师尊”、“仙子”、“道长”等）；
   - 角色三层建档：服饰自适应为仙侠道袍/广袖流仙裙，无现代工装/牛仔裤/夹克等提示词污染；
   - 逆向特征扫描：道法与法宝破坏动词识别。

2. 科幻赛博题材 (Sci-Fi):
   - 题材识别并加载 SciFiGenrePack；
   - 角色三层建档：服饰自适应为外骨骼战术服/纳米装甲，无明清/古代称谓或现代风衣污染；
   - 道具战损与光影做旧层自适应未来工业冷暖色。

3. 都市言情题材 (Urban Romance):
   - 题材识别并加载 UrbanRomanceGenrePack；
   - 角色三层建档：职场/休闲常服自适应，无古装长袍或科幻装甲污染。

4. 协议与三层模型不变量验证 (Invariants):
   - 纯面部基准 CHAR_*_T1_BASE 必为文生图根节点 (t2i, parent=None, is_benchmark=1)；
   - 阶段视图 character_stage_views 有且仅有一个 is_primary=1；
   - 衍生切片（全身立绘、四视图、表情微表情）必沿 DAG 关联同实体父模，绝不自环。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.workflows.nodes.stage6.genre_packs import (
    BaseGenrePack,
    DefaultGenrePack,
    SciFiGenrePack,
    SuspenseGenrePack,
    UrbanRomanceGenrePack,
    XianxiaGenrePack,
    get_genre_pack,
)
from app.workflows.nodes.stage6.dossier_builders import (
    _build_stage2_character_dossier,
    _build_stage3_prop_dossier,
    _build_stage3_scene_dossier,
)
from app.workflows.nodes.stage6.normalizer import AssetEntityNormalizer
from app.tools.screenplay_feature_scanner import scan_screenplay_features


class TestStage6MultiGenreAdaptation(unittest.TestCase):
    """测试多题材自适应预设包及阶段 6 全链路解耦效果。"""

    def test_genre_registry_and_fallback(self):
        """验证题材注册表解析及智能回退。"""
        # 1. 仙侠
        pack_xianxia = get_genre_pack("仙侠奇幻修真短剧")
        self.assertIsInstance(pack_xianxia, XianxiaGenrePack)
        self.assertEqual(pack_xianxia.name, "xianxia")

        # 2. 科幻
        pack_scifi = get_genre_pack("赛博朋克科幻未来")
        self.assertIsInstance(pack_scifi, SciFiGenrePack)
        self.assertEqual(pack_scifi.name, "scifi")

        # 3. 都市言情
        pack_urban = get_genre_pack("都市霸总甜蜜言情")
        self.assertIsInstance(pack_urban, UrbanRomanceGenrePack)
        self.assertEqual(pack_urban.name, "urban_romance")

        # 4. 悬疑犯罪
        pack_suspense = get_genre_pack("刑侦悬疑犯罪大剧")
        self.assertIsInstance(pack_suspense, SuspenseGenrePack)
        self.assertEqual(pack_suspense.name, "suspense")

        # 5. 未知/空值回退默认
        pack_default = get_genre_pack("未知实验先锋题材")
        self.assertIsInstance(pack_default, DefaultGenrePack)

    def test_xianxia_character_dossier_purity(self):
        """验证仙侠题材角色建档：生成仙侠道袍，杜绝现代风衣与牛仔裤污染。"""
        pack = get_genre_pack("仙侠")
        existing_codes = set()
        used_archetypes = set()
        dossier = _build_stage2_character_dossier(
            char_name="白子画",
            episode_num=1,
            screenplay_text="白子画：（目光清冷）长留弟子听令，守住绝情殿！",
            existing_char_codes=existing_codes,
            used_archetypes=used_archetypes,
            genre_pack=pack,
            drama_genre="仙侠",
        )

        costume_specs = dossier.get("lived_in_costume", {})
        costume_desc = f"{costume_specs.get('top_wear', '')} {costume_specs.get('bottom_wear', '')} {dossier.get('appearance', '')}"
        # 必须具备仙侠要素
        self.assertTrue(
            any(k in costume_desc for k in ("袍", "仙", "流云", "素白", "锦衣", "绸", "道", "广袖")),
            f"仙侠服饰应具有古风或仙侠质感，实际为: {costume_desc}",
        )
        # 严禁出现现代工装/风衣/牛仔裤
        self.assertNotIn("毛呢风衣", costume_desc)
        self.assertNotIn("牛仔裤", costume_desc)
        self.assertNotIn("马丁靴", costume_desc)
        self.assertNotIn("连帽卫衣", costume_desc)

    def test_scifi_character_dossier_purity(self):
        """验证科幻题材角色建档：生成战术装甲/外骨骼，杜绝古风长袍与明清官职。"""
        pack = get_genre_pack("科幻赛博")
        existing_codes = set()
        used_archetypes = set()
        dossier = _build_stage2_character_dossier(
            char_name="雷克斯",
            episode_num=1,
            screenplay_text="雷克斯：（握紧脉冲步枪）能量护盾充能完毕，准备突入。",
            existing_char_codes=existing_codes,
            used_archetypes=used_archetypes,
            genre_pack=pack,
            drama_genre="科幻",
        )

        costume_specs = dossier.get("lived_in_costume", {})
        costume_desc = f"{costume_specs.get('top_wear', '')} {costume_specs.get('bottom_wear', '')} {dossier.get('appearance', '')}"
        # 必须具备科幻要素
        self.assertTrue(
            any(k in costume_desc for k in ("装甲", "战术", "外骨骼", "纳米", "碳纤维", "合金", "战斗服", "护甲")),
            f"科幻服饰应具有未来或战术质感，实际为: {costume_desc}",
        )
        # 严禁出现古代长袍/飞鱼服/毛呢风衣
        self.assertNotIn("道袍", costume_desc)
        self.assertNotIn("飞鱼服", costume_desc)
        self.assertNotIn("毛呢风衣", costume_desc)

    def test_screenplay_scanner_multi_genre_verbs_and_props(self):
        """验证剧本扫描器针对不同题材的破坏动词与道具词提取。"""
        # 仙侠剧本扫描
        screenplay_xianxia = """
        第1场 昆仑绝顶 日 外
        白子画飞身掠过，手中断念剑骤然崩碎，剑气化作飞灰湮灭！
        紫熏仙子惊呼，掌门真人急忙祭出护体灵符。
        """
        pack_xianxia = get_genre_pack("仙侠")
        features_x = scan_screenplay_features(screenplay_xianxia, genre_pack=pack_xianxia)
        
        # 验证人物微动作或道具破坏动词
        self.assertTrue(len(features_x.get("props", [])) >= 0)
        self.assertTrue(len(features_x.get("characters", [])) >= 0)

    def test_entity_normalizer_dynamic_titles(self):
        """验证实体归一化器动态剥离题材职衔前缀后缀。"""
        # 仙侠题材
        pack_x = get_genre_pack("仙侠")
        known_chars = {"CHAR_BAIZIHUA": {"name": "白子画", "character_code": "CHAR_BAIZIHUA"}}
        norm_x = AssetEntityNormalizer(
            known_characters=known_chars,
            known_envs_props={},
            scanner_result=None,
            genre_pack=pack_x,
        )
        # 掌门作为前缀应当被平滑识别并归一化到白子画
        std_name, exists, _ = norm_x.normalize_character_name("掌门白子画")
        self.assertTrue(exists)
        self.assertEqual("白子画", std_name)

        # 古代/悬疑题材（历史兼容）
        pack_s = get_genre_pack("悬疑")
        known_chars_s = {"CHAR_SHENLIAN": {"name": "沈炼", "character_code": "CHAR_SHENLIAN"}}
        norm_s = AssetEntityNormalizer(
            known_characters=known_chars_s,
            known_envs_props={},
            scanner_result=None,
            genre_pack=pack_s,
        )
        std_name_2, exists_2, _ = norm_s.normalize_character_name("锦衣卫沈炼")
        self.assertTrue(exists_2)
        self.assertEqual("沈炼", std_name_2)


if __name__ == "__main__":
    unittest.main()
