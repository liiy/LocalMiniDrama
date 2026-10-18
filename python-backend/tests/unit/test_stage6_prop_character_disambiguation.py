"""单元测试：两程九阶阶段 6 道具与角色消歧归纳专项测试。

验证内容：
1. 剧本中【带血的牛皮纸信封】与后文动作行“信封”识别为同一物证，拦截独立拆分并实施动作语料冒泡；
2. 排他性修饰语相斥检测（例如“白色信封”与“带血的牛皮纸信封”不误合并）；
3. 角色叠词爱称与职衔消歧归纳（“晚晚” -> “林晚”，“周队长” -> “周衍”）；
4. 同姓多角色歧义自动熔断保护（“周衍”与“周正国”共存时，“周队”不胡乱合并）；
5. 泛化亲属与社会职业称谓（“伯母”、“阿姨”）拦截不建档。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.tools.screenplay_feature_scanner import (
    ScreenplayFeatureScanner,
    is_valid_character_speaker,
)
from app.workflows.nodes.stage6.normalizer import AssetEntityNormalizer
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.step5_dossier import IncrementalDossierStep
from app.workflows.nodes.stage6.steps.step6_slices import SliceDerivationStep
from app.schemas.script_graph_state import IndustrialDramaMasterState


class TestStage6PropCharacterDisambiguation(unittest.TestCase):
    """阶段 6 资产真理源消歧与防呆归一测试集。"""

    def setUp(self) -> None:
        """准备用户真实输入的经典多交锋剧本文本。"""
        self.screenplay_text = """【场景 01】内景. 苏秀兰旧居灵堂 - 深夜 - 昏暗钨丝灯与惨白雨夜光
[声学行为: 开场突发重击 Braam Hit]
△ 【开局3秒抓手】灵堂棺木前生锈铁盆内的黄纸骤然被穿堂阴风吹散，一只【带血的牛皮纸信封】啪地甩在苏秀兰黑白遗像玻璃框上，玻璃当场震出细裂纹。
△ 林晚猛地跨前一步，指节发白地将信封从裂开的镜框上狠狠扯下。
△ 周衍身穿深蓝执勤夹克立在供桌旁，将厚重的【苏秀兰坠楼案自杀结案卷宗】推向桌面中央。
周衍（双手紧握脱漆保温杯，喉腔沉闷发紧）：签了这份自杀确认书，让伯母早点入土为安。
林晚（左手拇指死扣右手腕银手链，声线偏冷下坠）：新闻只认证据，不认眼泪。
△ 周衍从卷宗夹层抽出一张泛黄的【抑郁症处方笺】，重重拍在油腻的供桌上。
周衍（大拇指用力刮蹭保温杯盖脱漆边缘，语速沉缓）：法医的病历清清楚楚，坠楼前半年她就患病了。
林晚（下颌咬肌隆起，齿缝间挤出微颤冷气）：你们习惯了沉默，不代表事情没发生过。
△ 林晚指尖发力刺破信封干硬的纸边，刺啦一声撕开封口。
△ 【45秒微反转】林晚翻转信封，一张按着鲜红血指印的【老邮局挂号信寄件存根小联】滑落掌心，寄出时间赫然印着坠楼前两小时。
[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]
△ 周衍低头看清存根上的紫色机打时间，双眼瞳孔骤然缩紧。
周衍（喉头剧烈上下滚动，声带沙哑收紧）：说话要有法律依据，我只认结案报告。
林晚（抬眼逼视周衍双眸，字字如冰断崖下坠）：一个要寻死的人，会在跳楼前两小时去寄信？
△ 周衍跨步上前伸手抓向存根，林晚后撤半步侧身避开，风衣下摆撞落桌角纸灰。
周衍（右手食指死死按住战术皮带，压低气音低吼）：林晚，查下去整座城都要塌，你负得起责任吗？
林晚（左手指甲深陷手腕皮肉泛白，声线冷硬如铁）：我只负责把盖在棺材上的黑布掀开。
△ 林晚拔出金属手电筒推上开关，惨白光束笔直穿透信封内层折叠的信纸。
△ 【115秒片尾悬念】手电强光穿透信纸，纸面赫然渗出一行干涸暗红血字「晚晚，杀我的人正坐在我的追悼会主宾席上」，门外走廊骤然响起周正国沉重缓慢的皮鞋脚步声。
[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"""

    def test_scanner_prop_stem_deduplication_and_evidence_bubbling(self):
        """【测试 1】扫描器逆向特征提取：带血牛皮纸信封与后文动作'信封'消歧归一，语料冒泡。"""
        scan_res = ScreenplayFeatureScanner.scan(self.screenplay_text)
        props = scan_res.props_detected

        # 1. 验证【带血的牛皮纸信封】成功提取
        self.assertIn("带血的牛皮纸信封", props)

        # 2. 验证裸词“信封”作为从属简写未被拆分为独立新道具
        self.assertNotIn("信封", props, "简写词'信封'应被词干消歧合并入母物证，严禁独立存在")

        # 3. 验证动作行中的破坏动词（撕开、撕）被母物证捕获并成功激活 ACTION 破坏态
        deformed_props = scan_res.deformed_props
        envelope_verbs = deformed_props.get("带血的牛皮纸信封", [])
        self.assertTrue(
            any("撕" in v for v in envelope_verbs),
            f"动作行破坏动词未冒泡至母物证 deformed_props: {deformed_props}",
        )
        # 验证生成的资产中存在破坏态 (ACTION)
        action_assets = [a for a in scan_res.newly_generated_assets if "DAIXUEDENIUPIZHIXINFENG" in a.asset_id and "ACTION" in a.asset_id]
        self.assertTrue(len(action_assets) > 0, "母物证未因冒泡的破坏动词派生出 ACTION 破坏态切片")

    def test_scanner_non_character_speaker_filtering(self):
        """【测试 2】泛化亲属与社会职业称谓（伯母、阿姨、师傅等）拦截。"""
        # 台词提及“伯母”，不应被当作有效角色对白发言人
        self.assertFalse(is_valid_character_speaker("伯母"))
        self.assertFalse(is_valid_character_speaker("阿姨"))
        self.assertFalse(is_valid_character_speaker("师傅"))
        self.assertFalse(is_valid_character_speaker("服务员"))

        # 具名角色应当正常通过
        self.assertTrue(is_valid_character_speaker("林晚"))
        self.assertTrue(is_valid_character_speaker("周衍"))

    def test_normalizer_prop_modifier_exclusion(self):
        """【测试 3】排他性修饰语检测：防止同类不同道具误合并。"""
        existing_props = {"带血的牛皮纸信封", "金属手电筒"}

        # 1. 裸词'信封'或词干'牛皮纸信封' -> 安全归纳至'带血的牛皮纸信封'
        self.assertEqual(
            AssetEntityNormalizer.resolve_prop_name("信封", existing_props),
            "带血的牛皮纸信封",
        )
        self.assertEqual(
            AssetEntityNormalizer.resolve_prop_name("牛皮纸信封", existing_props),
            "带血的牛皮纸信封",
        )

        # 2. 带有相斥修饰词的道具（如'白色信封'、'黑色信封'） -> 严禁合并，保持独立！
        self.assertEqual(
            AssetEntityNormalizer.resolve_prop_name("白色信封", existing_props),
            "白色信封",
            "具有排他性颜色修饰的白色信封不应与带血牛皮纸信封合并",
        )
        self.assertEqual(
            AssetEntityNormalizer.resolve_prop_name("塑料信封", existing_props),
            "塑料信封",
            "具有排他性材质修饰的塑料信封不应与牛皮纸信封合并",
        )

    def test_normalizer_character_disambiguation_and_homophone_guard(self):
        """【测试 4】角色叠词爱称归纳与同姓多实体歧义自动熔断。"""
        # 场景 A: 单个角色林晚，'晚晚'为叠词爱称
        chars_a = {"林晚"}
        self.assertEqual(
            AssetEntityNormalizer.resolve_character_name("晚晚", chars_a),
            "林晚",
            "叠词爱称'晚晚'应安全归纳为'林晚'",
        )
        self.assertEqual(
            AssetEntityNormalizer.resolve_character_name("小林晚", chars_a),
            "林晚",
        )

        # 场景 B: 单个周姓角色周衍，'周队'或'周警官'安全归纳
        chars_b = {"周衍"}
        self.assertEqual(
            AssetEntityNormalizer.resolve_character_name("周队", chars_b),
            "周衍",
        )
        self.assertEqual(
            AssetEntityNormalizer.resolve_character_name("周警官", chars_b),
            "周衍",
        )

        # 场景 C: 同姓多实体歧义熔断（同时存在'周衍'与'周正国'）
        chars_c = {"周衍", "周正国"}
        resolved_zhou = AssetEntityNormalizer.resolve_character_name("周队", chars_c)
        self.assertEqual(
            resolved_zhou,
            "周队",
            "存在周衍和周正国两位同姓角色时，单字'周'模糊匹配必须熔断，防止父子角色串号",
        )

    def test_step5_and_step6_prop_consolidation_flow(self):
        """【测试 5】Step 5 / Step 6 全链路道具建档与切片收敛。"""
        state = IndustrialDramaMasterState(
            drama_id=999,
            current_visual_episode=1,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "灵堂交锋",
                    "screenplay_text": self.screenplay_text,
                }
            },
            characters_engine={"characters": [{"character_id": "CHAR_LINWAN", "name": "林晚"}]},
            environments_and_props={
                "environments": [{"environment_id": "ENV_LINGTANG", "location_name": "苏秀兰旧居灵堂"}],
                "props": [],
            },
        )
        ctx = Stage6StepContext(state=state)
        ctx.scanner_result = ScreenplayFeatureScanner.scan(self.screenplay_text)

        # 模拟大模型上报了【带血的牛皮纸信封】和动作中简化的【信封】
        ctx.extracted_assets_raw = {
            "episode_resource_manifest": {
                "characters": [{"name": "林晚"}, {"name": "周衍"}],
                "environments": [{"location_name": "苏秀兰旧居灵堂"}],
                "props": [
                    {
                        "name": "带血的牛皮纸信封",
                        "prop_name": "带血的牛皮纸信封",
                        "screenplay_evidence": "一只【带血的牛皮纸信封】啪地甩在苏秀兰黑白遗像玻璃框上",
                    },
                    {
                        "name": "信封",
                        "prop_name": "信封",
                        "screenplay_evidence": "林晚指尖发力刺破信封干硬的纸边，刺啦一声撕开封口",
                        "deformation_verbs": ["撕开", "刺破"],
                    },
                ],
            }
        }

        # 运行步骤 5：增量建档
        step5 = IncrementalDossierStep()
        step5.run(ctx)

        # 验证步骤 5 建档产物中，道具列表中只建立了【带血的牛皮纸信封】，而'信封'被作为别名合并并冒泡了证据
        created_props = ctx.dossier_new_props
        prop_names = [p.get("name") for p in created_props]
        self.assertIn("带血的牛皮纸信封", prop_names)
        self.assertNotIn("信封", prop_names, "步骤 5 必须拦截简写'信封'的独立建档")

        envelope_dossier = next(p for p in created_props if p.get("name") == "带血的牛皮纸信封")
        self.assertIn("信封", envelope_dossier.get("aliases", []))
        self.assertTrue(
            "撕开" in envelope_dossier.get("screenplay_evidence", "") or "刺破" in envelope_dossier.get("screenplay_evidence", ""),
            "步骤 5 应完成语料冒泡合并 (Action Corpus Bubbling)",
        )

        # 运行步骤 6：切片派生
        step6 = SliceDerivationStep()
        step6.run(ctx)

        # 验证最终派生的切片中只有以全称命名的 PROP 资产
        final_slices = ctx.derived_slices
        final_prop_keys = [
            s.get("asset_id") or s.get("prop_id")
            for s in final_slices
            if (s.get("asset_id") or "").startswith("PROP_") or (s.get("prop_id") or "").startswith("PROP_")
        ]

        # 应该存在 PROP_DAIXUEDENIUPIZHIXINFENG_T1_HERO / STATIC 等
        self.assertTrue(
            any("DAIXUEDENIUPIZHIXINFENG" in k for k in final_prop_keys),
            f"未找到全称道具资产: {final_prop_keys}",
        )
        # 绝不能存在单调缺失视觉特征的 PROP_XINFENG 系列切片
        self.assertFalse(
            any(k.startswith("PROP_XINFENG_") for k in final_prop_keys),
            f"切片派生泄露了残缺简写资产: {final_prop_keys}",
        )


if __name__ == "__main__":
    unittest.main()
