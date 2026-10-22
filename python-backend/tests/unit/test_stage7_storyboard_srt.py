"""测试阶段 7 分镜双模式选型与毫秒级 SRT 输出（严格四段式资产对齐与哨卡自审）。"""
import unittest

from app.agents.red_blue_auditor import RedBlueAuditor
from app.schemas.script_graph_state import IndustrialDramaMasterState, StoryboardShot
from app.workflows.nodes.stage7_storyboard_srt import stage7_storyboard_srt_node
from app.workflows.utils.asset_protocol import AssetProtocolHelper


class TestStage7StoryboardSRT(unittest.TestCase):
    def test_storyboard_and_srt_generation(self):
        state = IndustrialDramaMasterState(
            drama_id=666,
            current_visual_episode=1,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "生死突围",
                    "hook_3s": "开局枪口顶头",
                    "body_markdown": "对白交锋...",
                    "ending_cliffhanger": "后视镜浮现面孔",
                }
            },
            characters_engine={
                "characters": [
                    {"name": "陆沉", "character_token": "LUCHEN"},
                    {"name": "沈墨", "character_token": "SHENMO"},
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "核心仓库", "scene_token": "CANGKU"}],
                "props": [{"name": "加密信件", "prop_token": "LETTER"}],
            },
        )

        res = stage7_storyboard_srt_node(state)
        self.assertEqual(res["current_stage"], 7)
        storyboards = res["episode_storyboards"]
        self.assertIn(1, storyboards)
        shots = storyboards[1]
        self.assertTrue(len(shots) >= 2)

        # 检查是否包含模式 A 与模式 B
        modes = [s.generation_mode for s in shots]
        self.assertIn("first_last_frame", modes)
        self.assertIn("multi_image_reference", modes)

        # 检查四段式资产引用合规性
        for s in shots:
            if s.generation_mode == "first_last_frame" and s.first_last_config:
                ff_id = s.first_last_config.get("first_frame_asset_id")
                lf_id = s.first_last_config.get("last_frame_asset_id")
                if ff_id:
                    valid, _ = AssetProtocolHelper.validate_id(ff_id)
                    self.assertTrue(valid, f"首帧资产 ID 非标: {ff_id}")
                if lf_id:
                    valid, _ = AssetProtocolHelper.validate_id(lf_id)
                    self.assertTrue(valid, f"尾帧资产 ID 非标: {lf_id}")

            if s.generation_mode == "multi_image_reference" and s.multi_image_config:
                refs = s.multi_image_config.get("reference_asset_ids") or []
                for r in refs:
                    valid, _ = AssetProtocolHelper.validate_id(r)
                    self.assertTrue(valid, f"参考资产 ID 非标: {r}")

        # 检查红蓝对抗哨卡 7 审查通过
        audit_report = RedBlueAuditor.audit_stage7({"shots": shots})
        if audit_report.blocking_issues:
            print(f"!!! DEBUG BLOCKING ISSUES: {audit_report.blocking_issues}")
        self.assertEqual(audit_report.verdict, "GREEN_APPROVED")
        self.assertEqual(len(audit_report.blocking_issues), 0)

        # 检查 SRT 字幕
        srts = res["episode_srt_exports"]
        self.assertIn(1, srts)
        self.assertIn("-->", srts[1])

    def test_mourning_hall_script_grounding_and_no_gun_hallucination(self):
        """测试用户反馈的灵堂剧本在阶段7分镜中实现精准语义对齐，坚决绝迹虚构枪械。"""
        from app.workflows.nodes.script_beat_extractor import ScriptBeatExtractor
        from app.workflows.nodes.stage7_storyboard_srt import SemanticGroundingGuard

        script_text = (
            "【场景 01】内景. 苏秀兰旧居灵堂 - 深夜 - 昏暗钨丝灯与惨白雨夜光\n"
            "[声学行为: 开场突发重击 Braam Hit]\n"
            "△ 【开局3秒抓手】灵堂棺木前生锈铁盆内的黄纸骤然被穿堂阴风吹散，一只【带血的牛皮纸信封】啪地甩在苏秀兰黑白遗像玻璃框上，玻璃当场震出细裂纹。\n"
            "△ 林晚猛地跨前一步，指节发白地将信封从裂开的镜框上狠狠扯下。\n"
            "△ 周衍身穿深蓝执勤夹克立在供桌旁，将厚重的【苏秀兰坠楼案自杀结案卷宗】推向桌面中央。\n"
            "周衍（双手紧握脱漆保温杯，喉腔沉闷发紧）：签了这份自杀确认书，让伯母早点入土为安。\n"
            "林晚（左手拇指死扣右手腕银手链，声线偏冷下坠）：新闻只认证据，不认眼泪。\n"
            "△ 周衍从卷宗夹层抽出一张泛黄的【抑郁症处方笺】，重重拍在油腻的供桌上。\n"
            "周衍（大拇指用力刮蹭保温杯盖脱漆边缘，语速沉缓）：法医的病历清清楚楚，坠楼前半年她就患病了。\n"
            "林晚（下颌咬肌隆起，齿缝间挤出微颤冷气）：你们习惯了沉默，不代表事情没发生过。\n"
            "△ 林晚指尖发力刺破信封干硬的纸边，刺啦一声撕开封口。\n"
            "△ 【45秒微反转】林晚翻转信封，一张按着鲜红血指印的【老邮局挂号信寄件存根小联】滑落掌心，寄出时间赫然印着坠楼前两小时。\n"
            "[声学行为: 核心戏剧骤停，进入主观绝对物理静音 2.5 秒]\n"
            "△ 周衍低头看清存根上的紫色机打时间，双眼瞳孔骤然缩紧。\n"
            "周衍（喉头剧烈上下滚动，声带沙哑收紧）：说话要有法律依据，我只认结案报告。\n"
            "林晚（抬眼逼视周衍双眸，字字如冰断崖下坠）：一个要寻死的人，会在跳楼前两小时去寄信？\n"
            "△ 周衍跨步上前伸手抓向存根，林晚后撤半步侧身避开，风衣下摆撞落桌角纸灰。\n"
            "周衍（右手食指死死按住战术皮带，压低气音低吼）：林晚，查下去整座城都要塌，你负得起责任吗？\n"
            "林晚（左手指甲深陷手腕皮肉泛白，声线冷硬如铁）：我只负责把盖在棺材上的黑布掀开。\n"
            "△ 林晚拔出金属手电筒推上开关，惨白光束笔直穿透信封内层折叠的信纸。\n"
            "△ 【115秒片尾悬念】手电强光穿透信纸，纸面赫然渗出一行干涸暗红血字「晚晚，杀我的人正坐在我的追悼会主宾席上」，门外走廊骤然响起周正国沉重缓慢的皮鞋脚步声。\n"
            "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
        )

        # 1. 验证 AST / 正则视听原子抽取器能力
        ctx = ScriptBeatExtractor.extract(script_text)
        self.assertIn("灵堂棺木前生锈铁盆内的黄纸骤然被穿堂阴风吹散", ctx["hook_3s_action"])
        self.assertIn("周衍", ctx["involved_characters"])
        self.assertIn("林晚", ctx["involved_characters"])
        self.assertTrue(len(ctx["dialogues"]) >= 4)
        self.assertEqual(ctx["dialogues"][0]["speaker"], "周衍")
        self.assertIn("自杀确认书", ctx["dialogues"][0]["dialogue_text"])
        self.assertEqual(ctx["dialogues"][1]["speaker"], "林晚")
        self.assertIn("新闻只认证据", ctx["dialogues"][1]["dialogue_text"])

        # 2. 验证分镜生成节点真实执行时，全面杜绝“枪口顶在额头”
        state = IndustrialDramaMasterState(
            drama_id=888,
            current_visual_episode=1,
            target_video_engine="wan3.0",
            duration_sec_per_ep=120.0,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "灵堂交锋",
                    "hook_3s": ctx["hook_3s_action"],
                    "body_markdown": script_text,
                    "ending_cliffhanger": ctx.get("ending_cliffhanger", "片尾悬念"),
                }
            },
            characters_engine={
                "characters": [
                    {"name": "林晚", "character_token": "LINWAN"},
                    {"name": "周衍", "character_token": "ZHOUYAN"},
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "苏秀兰旧居灵堂", "scene_token": "LINGTANG"}],
                "props": [{"name": "带血的牛皮纸信封", "prop_token": "ENVELOPE"}],
            },
        )

        res = stage7_storyboard_srt_node(state)
        shots = res["episode_storyboards"][1]

        # 验证提示词中绝无虚构枪械
        for s in shots:
            img_p = getattr(s, "image_prompt", "") or ""
            vid_p = getattr(s, "video_prompt", "") or ""
            flc = getattr(s, "first_last_config", {}) or {}
            ff_p = flc.get("first_frame_prompt", "") if isinstance(flc, dict) else ""
            self.assertNotIn("枪口", img_p)
            self.assertNotIn("枪口", vid_p)
            self.assertNotIn("顶在额头", img_p)
            self.assertNotIn("顶在额头", ff_p)

        # 验证镜头 1 紧扣灵堂或信封黄纸动作
        shot1 = shots[0]
        shot1_text = f"{shot1.image_prompt} {shot1.video_prompt}"
        self.assertTrue(
            any(w in shot1_text for w in ["灵堂", "信封", "黄纸", "苏秀兰", "遗像", "棺木", "铁盆"]),
            f"镜头1应锚定灵堂与信封，实际提示词: {shot1_text}"
        )

        # 验证字幕准确包含周衍与林晚对白
        srt_text = res["episode_srt_exports"][1]
        self.assertTrue(
            "周衍" in srt_text or "自杀确认书" in srt_text or "林晚" in srt_text or "新闻只认证据" in srt_text,
            f"SRT字幕应紧扣灵堂剧本对白，实际输出: {srt_text}"
        )

    def test_semantic_grounding_guard_interception(self):
        """测试语义审查守卫在遇到幻觉枪械时，强制触发自愈拦截并纠偏为剧本动作。"""
        from app.workflows.nodes.stage7_storyboard_srt import SemanticGroundingGuard

        mock_shot = {
            "shot_id": 1,
            "image_prompt": "电影级极特写，冰冷枪口顶在主角额头，冷调边缘光",
            "video_prompt": "镜头向前推，枪口用力压迫额头，神色紧绷",
            "first_last_config": {
                "first_frame_prompt": "冰冷手枪瞄准主角面部",
                "last_frame_prompt": "手指扣动扳机瞬间",
            },
            "audio": {
                "foley": "[Foley+3dB: 沉闷拔枪与子弹上膛声]",
            },
        }

        mock_ctx = {
            "scene_header": "【场景 01】苏秀兰灵堂",
            "hook_3s_action": "阴风吹散黄纸，一只带血的牛皮纸信封甩在遗像玻璃框上",
            "actions": [
                "阴风吹散黄纸，一只带血的牛皮纸信封甩在遗像玻璃框上",
                "林晚狠狠撕开信封",
            ],
            "dialogues": [],
        }

        # 剧本全文无枪
        script_full_text = "苏秀兰灵堂，林晚撕开带血信封..."
        triggered = SemanticGroundingGuard.audit_and_sanitize_shot(
            mock_shot,
            script_context=mock_ctx,
            script_full_text=script_full_text,
        )

        self.assertTrue(triggered, "守卫应检测到虚构枪械并触发拦截纠偏")
        self.assertNotIn("枪口", mock_shot["image_prompt"])
        self.assertNotIn("额头", mock_shot["image_prompt"])
        self.assertIn("阴风吹散黄纸", mock_shot["image_prompt"])
        self.assertNotIn("子弹上膛", mock_shot["audio"]["foley"])

    def test_first_last_frame_4d_audio_visual_and_decoupling(self):
        """测试模式 A 首尾帧 4D 视听插值提示词生成以及与外部音频解耦标记。"""
        from app.workflows.nodes.stage7_storyboard_srt import (
            _compile_first_last_frame_prompts,
            _enforce_canonical_shot_resource_order,
        )

        mock_shot = {
            "shot_id": 1,
            "duration_sec": 4.0,
            "framing": "MCU 中近景",
            "camera_motion": "水平缓慢向右平移",
            "generation_mode": "first_last_frame",
            "image_prompt": "灵堂棺木前，林晚神色冷峻，指节发白",
            "audio": {
                "dialogue": "",
                "ambient": "暴风雨夜穿堂风呼啸，烛火摇曳噼啪声",
                "foley": "[Foley+3dB: 牛皮纸信封被阴风吹散撞击相框沉闷响声]",
                "music": "压抑弦乐持续低鸣",
            },
            "first_last_config": {
                "first_frame_asset_id": "ENV_MATOU_T1_WIDE",
                "last_frame_asset_id": "CHAR_LINWAN_T1_BASE_PORTRAIT",
                "first_frame_prompt": "灵堂棺木前生锈铁盆黄纸被穿堂风吹散",
                "last_frame_prompt": "信封甩在遗像玻璃框上震出裂纹，林晚猛地跨前半步",
                "video_motion_prompt": "",
            },
        }

        # 执行标准化槽位与首尾帧 4D 提示词编译
        _enforce_canonical_shot_resource_order(mock_shot)
        _compile_first_last_frame_prompts(mock_shot)

        # 转换为 StoryboardShot 模型进行契约校验
        shot_obj = StoryboardShot.model_validate(mock_shot)

        self.assertEqual(shot_obj.generation_mode, "first_last_frame")
        self.assertTrue(shot_obj.audio_prompt_embedded, "首尾帧模式下 audio_prompt_embedded 应为 True")
        self.assertFalse(shot_obj.requires_external_synth, "首尾帧模式下 requires_external_synth 应为 False")

        # 检查 motion prompt 包含声学与物理插值
        motion_p = shot_obj.first_last_config.get("video_motion_prompt", "")
        self.assertIn("【首尾帧4D视听插值", motion_p)
        self.assertIn("空间声学铺底", motion_p)
        self.assertIn("动作拟音爆发", motion_p)
        self.assertIn("声场混响衰减", motion_p)

    def test_multi_image_ambient_and_foley_injection(self):
        """测试模式 B 多图生成视频全面注入环境声场、拟音音效与发话主体闭嘴约束。"""
        from app.workflows.nodes.stage7_storyboard_srt import compile_engine_video_prompt

        # 1. Wan 3.0 引擎多图视听编译
        wan_prompt = compile_engine_video_prompt(
            target_engine="wan3.0",
            scene_symbol="图1",
            subject_symbol="图2",
            counterpart_symbol="图3",
            action_desc="眼神逼视，指节发白",
            dialogue_audio_symbol="音频1",
            ambient_sound="灵堂风声呼啸与烛火噼啪声",
            foley_sound="信封撕裂刺啦声",
            prop_symbol="图4",
        )
        self.assertIn("空间声场铺底（灵堂风声呼啸与烛火噼啪声）", wan_prompt)
        self.assertIn("伴随物理拟音音效（信封撕裂刺啦声）", wan_prompt)
        self.assertIn("[说话主体: 图2] 开口叙述（音频1）", wan_prompt)
        self.assertIn("同框 [倾听同伴: 图3] 紧闭双唇、目光冰冷凝视、不发一言", wan_prompt)
        self.assertIn("手中紧握物证 图4", wan_prompt)

        # 2. Seedance 2.5 模块化编译
        seedance_prompt = compile_engine_video_prompt(
            target_engine="seedance2.5",
            scene_symbol="图1",
            subject_symbol="图2",
            counterpart_symbol="图3",
            action_desc="眼神逼视，指节发白",
            dialogue_audio_symbol="音频1",
            ambient_sound="灵堂风声呼啸",
            foley_sound="信封撕裂声",
            prop_symbol="图4",
        )
        self.assertIn("[Environment]", seedance_prompt)
        self.assertIn("环境空间声场铺底（灵堂风声呼啸）", seedance_prompt)
        self.assertIn("物理动作伴随拟音爆发（信封撕裂声）", seedance_prompt)
        self.assertIn("[说话主体: 图2] 同步开口说话（音频1）", seedance_prompt)
        self.assertIn("[倾听角色: 图3] 紧闭双唇保持静默、不发一言", seedance_prompt)

        # 3. MiniMax H3 叙述流编译
        minimax_prompt = compile_engine_video_prompt(
            target_engine="minimax_h3",
            scene_symbol="图1",
            subject_symbol="图2",
            counterpart_symbol="图3",
            action_desc="眼神逼视",
            dialogue_audio_symbol="音频1",
            ambient_sound="低频轰鸣",
            foley_sound="撞击重击",
            prop_symbol="图4",
        )
        self.assertIn("（空间弥漫着低频轰鸣）", minimax_prompt)
        self.assertIn("动作爆发伴随物理接触音（撞击重击）", minimax_prompt)
        self.assertIn("[说话主体: 图2] 低沉开口说道（音频1）", minimax_prompt)
        self.assertIn("同框 [同伴: 图3] 紧闭双唇保持肃穆无言", minimax_prompt)

    def test_dynamic_full_beat_fallback_compiler(self):
        """测试阶段7在降级模式下全量编译剧本所有节拍，彻底告别硬编码3镜头。"""
        from app.workflows.nodes.stage7_storyboard_srt import _stage7_fallback

        script_text = """【场景 01】内景. 苏秀兰旧居灵堂 - 深夜 - 昏暗钨丝灯与惨白雨夜光
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

        state = IndustrialDramaMasterState(
            drama_id=888,
            current_visual_episode=1,
            completed_screenplays={
                1: {
                    "episode_num": 1,
                    "title": "灵堂交锋",
                    "hook_3s": "灵堂棺木前生锈铁盆内的黄纸骤然被穿堂阴风吹散",
                    "body_markdown": script_text,
                    "ending_cliffhanger": "周正国沉重缓慢的皮鞋脚步声",
                }
            },
            characters_engine={
                "characters": [
                    {"name": "林晚", "character_token": "LINWAN"},
                    {"name": "周衍", "character_token": "ZHOUYAN"},
                    {"name": "周正国", "character_token": "ZHOUZHENGGUO"},
                ]
            },
            environments_and_props={
                "environments": [{"location_name": "苏秀兰旧居灵堂", "scene_token": "SULAN_LINGTANG"}],
                "props": [
                    {"name": "带血的牛皮纸信封", "prop_token": "ENVELOPE"},
                    {"name": "自杀结案卷宗", "prop_token": "DOSSIER"},
                ],
            },
        )

        chars_list = [
            {"name": "林晚", "character_token": "LINWAN"},
            {"name": "周衍", "character_token": "ZHOUYAN"},
            {"name": "周正国", "character_token": "ZHOUZHENGGUO"},
        ]
        envs_list = [{"location_name": "苏秀兰旧居灵堂", "scene_token": "SULAN_LINGTANG"}]
        props_list = [
            {"name": "带血的牛皮纸信封", "prop_token": "ENVELOPE"},
            {"name": "自杀结案卷宗", "prop_token": "DOSSIER"},
        ]
        script_dict = {
            "episode_num": 1,
            "title": "灵堂交锋",
            "hook_3s": "灵堂棺木前生锈铁盆内的黄纸骤然被穿堂阴风吹散",
            "body_markdown": script_text,
            "ending_cliffhanger": "周正国沉重缓慢的皮鞋脚步声",
        }

        res = _stage7_fallback(
            episode_num=1,
            script_title="灵堂交锋",
            characters=chars_list,
            environments=envs_list,
            props=props_list,
            target_engine="kling",
            planned_duration_sec=120.0,
            script=script_dict,
        )
        shots = res["shots"]
        total_duration = sum(s["duration_sec"] for s in shots)

        # 验证彻底告别 3 个镜头，涵盖完整剧本 15~25 个镜头
        self.assertGreaterEqual(len(shots), 15, f"分镜数量应 >= 15，实际产生: {len(shots)}")
        self.assertLessEqual(len(shots), 25, f"分镜数量应 <= 25，实际产生: {len(shots)}")

        # 验证总时长满足 120s ± 6.0s 误差范围，且每个分镜均为离散整数秒
        self.assertTrue(
            abs(total_duration - 120.0) <= 6.0,
            f"总时长应在 120 ± 6.0s 之间，实际总时长: {total_duration}"
        )
        for s in shots:
            self.assertIn(
                round(s["duration_sec"], 1),
                [2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
                f"分镜 duration_sec 应属于离散整数秒集合，实际为: {s['duration_sec']}"
            )

        # 验证开局与片尾节拍完整保留
        first_shot = shots[0]
        self.assertEqual(first_shot["generation_mode"], "first_last_frame")
        self.assertIn("黄纸", f"{first_shot['image_prompt']} {first_shot['video_prompt']}")

        last_shot = shots[-1]
        self.assertIn("周正国", f"{last_shot['image_prompt']} {last_shot['video_prompt']}")

        # 验证对白均有对应镜头与字幕覆盖
        srt_content = res["srt_content"]
        self.assertIn("让伯母早点入土为安", srt_content)
        self.assertIn("新闻只认证据", srt_content)
        self.assertIn("杀我的人正坐在我的追悼会主宾席上", srt_content)


if __name__ == "__main__":
    unittest.main()
