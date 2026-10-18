"""现代悬疑/犯罪题材预设包 (Suspense & Crime Genre Pack)。

默认基准题材包，100% 保持与重构前一致的工装、冷峻骨相、金属信物与物证动词。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack


class SuspenseGenrePack(BaseGenrePack):
    """现代悬疑/犯罪题材预设包。"""

    @property
    def name(self) -> str:
        return "suspense"

    @property
    def label(self) -> str:
        return "现代悬疑/犯罪"

    @property
    def match_keywords(self) -> list[str]:
        return [
            "悬疑", "犯罪", "警匪", "律政", "谍战", "刑侦", "暗黑", "反恐", "推理", "探案",
            "卧底", "追凶", "命案", "法医", "密室", "冷峻", "硬汉", "硬派", "复仇",
        ]

    def get_character_bio(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        bone = "棱角分明的高颧骨与冷峻下颌线" if gender == "male" else "清隽骨相与清晰下颌折角"
        return {
            "bone_structure": bone,
            "skin_micro_texture": "真实自然毛孔肌理与微汗反光，拒绝塑料磨皮",
            "blemishes_and_scars": "眼角微细风霜纹与鼻翼自然暗影",
            "eye_lip_anatomy": "瞳孔深邃带血丝微光，唇纹清晰真实",
            "hair_texture": "略带湿气与风尘感的自然碎发层次",
        }

    def get_character_costume(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        return {
            "top_wear": "深灰哑光重磅工装夹克，肩线与手肘带真实穿着折痕",
            "bottom_wear": "深色直筒耐磨长裤，裤脚微沾灰尘",
            "footwear": "鞋面带细微刮痕的深色旧皮靴，双脚完整落地",
            "wear_and_tear_details": "领口与袖口边缘呈自然摩擦微起毛质感",
        }

    def get_character_anchor_item(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "item_name": f"{char_name}的随身信物",
            "physical_description": "边角磨损的深色金属随身物件，表面留有长年摩挲痕迹",
            "narrative_function": f"第{episode_num}集身份核验与动作交互锚点",
        }

    def get_character_psychology(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "want": f"在第{episode_num}集冲突现场保全自身筹码并试探对方底牌",
            "need": "在危机漩涡中守住核心秘密不被清算",
            "lie": "只要不先亮出底牌就能永远掌控局势主动权",
            "ghost": "曾因轻信承诺而卷入旧案风波",
        }

    def get_character_personality(
        self,
        char_name: str,
    ) -> str:
        return "行事审慎果决，言辞暗藏机锋，在利益与真相博弈中保持高度戒备"

    def get_scene_weathering_elements(
        self,
        scene_name: str,
    ) -> tuple[str, str]:
        material = "architectural structural elements, authentic textures and weathered building materials"
        desc = f"{scene_name}主体承重与硬装边界，带真实岁月侵蚀与岁月沉淀感"
        return material, desc

    def get_hero_prop_keywords(self) -> list[str]:
        return [
            "日记", "确认书", "病历", "合同", "录音笔", "药盒", "打火机", "账本", "钥匙", "档案", "信件",
            "手枪", "匕首", "U盘", "信封", "怀表", "短刀", "印章", "残卷", "弹壳", "指纹纸",
        ]

    def get_anchor_prop_keywords(self) -> list[str]:
        return ["打火机", "戒指", "手表", "创可贴", "钥匙", "红绳", "怀表", "吊坠", "眼镜", "钢笔"]

    def get_atmospheric_prop_keywords(self) -> list[str]:
        return ["茶杯", "碗筷", "纸巾", "白气", "烟雾", "积水", "灰尘", "烛台", "酒杯", "手电筒"]

    def get_deformation_verbs(self) -> list[str]:
        return [
            "撕", "砸", "切", "断", "烧", "挑开", "崩碎", "撬开", "撞烂", "撕页", "划破", "扯回",
            "摔碎", "焚毁", "斩断", "捏碎", "折断", "撕开", "按动", "染血", "点燃", "咬碎", "浸湿",
            "剥离", "摔在地上", "砸烂", "被踩碎", "划痕", "开裂", "崩口", "卷刃",
        ]

    def get_title_prefixes(self) -> list[str]:
        return ["警官", "队长", "医生", "主任", "律师", "教授", "法医", "侦探", "头儿", "局长", "老", "小", "阿"]

    def get_title_suffixes(self) -> list[str]:
        return ["警官", "队长", "医生", "主任", "律师", "教授", "法医", "局长", "哥", "姐", "叔", "伯", "师傅"]
