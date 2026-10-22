"""现代都市/言情甜宠题材预设包 (Urban & Romance Genre Pack)。

适用于都市职场、豪门恩怨、甜宠恋爱、青春校园等现代轻生活题材。
提供修身西装、法式羊绒、智能手机、精致钢笔与现代极简都市空间。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack


class UrbanRomanceGenrePack(BaseGenrePack):
    """现代都市/言情甜宠题材预设包。"""

    @property
    def name(self) -> str:
        return "urban_romance"

    @property
    def label(self) -> str:
        return "现代都市/言情甜宠"

    @property
    def match_keywords(self) -> list[str]:
        return [
            "甜宠", "都市", "言情", "职场", "总裁", "豪门", "校园", "青春", "恋爱", "现言",
            "商战", "家庭", "情感", "暖心", "轻喜", "治愈", "暗恋", "破镜重圆", "婚恋",
        ]

    def get_character_bio(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        bone = "线条挺拔清朗的面容与温和清晰的下颌折角" if gender == "male" else "柔和流畅的鹅蛋脸型或精致小巧下巴，灵动秀气"
        return {
            "bone_structure": bone,
            "skin_micro_texture": "健康通透白皙的自然微光肤质，富有天然血色感，真实清爽毛孔",
            "blemishes_and_scars": "眼下极淡的浅笑卧蚕与自然表情纹",
            "eye_lip_anatomy": "目光含情明亮，瞳仁澄澈生动，唇色自然饱满微润",
            "hair_texture": "蓬松自然微卷的柔顺发丝，修剪精致利落，带天然光泽",
        }

    def get_character_costume(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        top = "质感纯色羊绒双面大衣内搭炭灰高领针织衫，剪裁挺阔利落" if gender == "male" else "法式优雅收腰针织开衫内搭丝质柔和衬衫，色彩淡雅温婉"
        bottom = "垂感高定深色西装长裤" if gender == "male" else "米白色高腰垂坠长裙或修身九分直筒裤"
        shoes = "擦拭干净的黑色系带牛津皮鞋，整洁得体" if gender == "male" else "极简法式米色小羊皮低跟单鞋，轻盈优雅"
        return {
            "top_wear": top,
            "bottom_wear": bottom,
            "footwear": shoes,
            "wear_and_tear_details": "衣物平整挺括，领口与袖口做工精良，彰显都市生活品质",
        }

    def get_character_anchor_item(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "item_name": f"{char_name}的定制钢笔/腕表",
            "physical_description": "银色金属纤细机械腕表或精致签字笔，刻有专属英文缩写字母",
            "narrative_function": f"第{episode_num}集情感信物见证与职场身份特征标记",
        }

    def get_character_psychology(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "want": f"在第{episode_num}集职场考验与情感试探中证明自身价值，守住自尊底线",
            "need": "卸下自我保护的坚硬外壳，坦然接纳真诚的情感连接",
            "lie": "只要足够独立坚强，即使孤身一人也不会受到任何伤害",
            "ghost": "曾经因付出过多而换来忽视与失望的青涩回忆",
        }

    def get_character_personality(
        self,
        char_name: str,
    ) -> str:
        return "外表从容得体，内心细腻重情，待人礼貌克制，在原则问题上坚定不移"

    def get_scene_weathering_elements(
        self,
        scene_name: str,
    ) -> tuple[str, str]:
        # 针对包含灵堂、旧居、破旧、筒子楼、案发、停尸等特定场景，自适应保持写实与凝重质感，坚决杜绝轻奢硬装污染
        somber_keywords = ["灵堂", "旧居", "筒子楼", "案发", "废弃", "停尸", "病房", "墓", "老宅", "地下室", "破旧"]
        if any(kw in scene_name for kw in somber_keywords):
            material = "weathered walls, aged concrete, dim ambient lighting, somber atmospheric texture"
            desc = f"{scene_name}主体写实空间结构，墙面与地面呈现生活与岁月磨损痕迹，光影对比强烈沉重"
        else:
            material = "contemporary architectural finish, clean glass panels, warm wood cladding, natural stone surfaces"
            desc = f"{scene_name}主体现代建筑硬装边界，空间结构分明，带有自然光斑与真实生活使用痕迹"
        return material, desc

    def get_hero_prop_keywords(self) -> list[str]:
        return [
            "智能手机", "合同", "设计稿", "咖啡杯", "手提包", "车钥匙", "求职信", "录音笔",
            "日记本", "名片夹", "项链", "耳钉", "钥匙扣", "保温杯", "定制钢笔", "策划案",
        ]

    def get_anchor_prop_keywords(self) -> list[str]:
        return ["手机", "手表", "戒指", "手链", "项链", "发夹", "钥匙", "保温杯", "钢笔", "手帕"]

    def get_atmospheric_prop_keywords(self) -> list[str]:
        return ["咖啡杯", "绿植盆栽", "便签贴纸", "笔记本电脑", "马克杯", "台灯", "玻璃水杯", "香薰蜡烛"]

    def get_deformation_verbs(self) -> list[str]:
        return [
            "撕毁", "打翻", "摔在地上", "划破", "踩碎", "捏紧", "揉皱", "跌落", "碰倒", "沾湿",
            "震动", "按灭", "撕开",
        ]

    def get_title_prefixes(self) -> list[str]:
        return [
            "顾总", "陆总", "林总", "沈总", "总裁", "助理", "秘书", "经理", "总监", "店长",
            "学长", "学姐", "老", "小",
        ]

    def get_title_suffixes(self) -> list[str]:
        return [
            "总", "董", "特助", "秘书", "总监", "经理", "哥", "姐", "学长", "学姐", "小姐", "先生",
        ]

    def infer_character_gender_and_age(
        self,
        char_name: str,
        screenplay_context: str = "",
    ) -> tuple[str, int]:
        """【都市言情题材角色性别与年龄特异性推断】"""
        female_urban_tokens = {"学姐", "学妹", "闺蜜", "前女友", "女特助", "秘书", "千金", "少奶奶", "大小姐"}
        if any(tok in char_name for tok in female_urban_tokens):
            gender = "female"
        elif any(tok in char_name for tok in ("学长", "学弟", "总裁", "前男友", "特助", "少爷")):
            gender = "male"
        else:
            return super().infer_character_gender_and_age(char_name, screenplay_context)

        if any(tok in char_name for tok in ("董", "董事长", "老董事长", "管家")):
            age = 52
        elif any(tok in char_name for tok in ("总", "总裁", "总监", "经理")):
            age = 32
        elif any(tok in char_name for tok in ("学妹", "学弟", "实习生", "小助理")):
            age = 22
        else:
            age = 26
        return gender, age
