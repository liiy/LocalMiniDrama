"""古装玄幻/仙侠/武侠题材预设包 (Ancient & Xianxia Genre Pack)。

适用于仙侠、修真、玄幻、古装言情、武侠江湖等题材。
提供道袍长衫、云锦皂靴、佩剑玉佩、青石榫卯等符合东方美学的特征。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack


class XianxiaGenrePack(BaseGenrePack):
    """古装玄幻/仙侠题材预设包。"""

    @property
    def name(self) -> str:
        return "xianxia"

    @property
    def label(self) -> str:
        return "古装玄幻/仙侠/武侠"

    @property
    def match_keywords(self) -> list[str]:
        return [
            "仙侠", "修仙", "玄幻", "古装", "武侠", "神魔", "修真", "宗门", "剑道", "洪荒",
            "江湖", "朝堂", "宫斗", "侠客", "门派", "道友", "飞升", "转世", "前世", "剑客",
            "王爷", "公主", "魔尊", "师尊", "同道", "剑修", "明", "宋", "唐", "古代",
        ]

    def get_character_bio(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        bone = "道骨仙风之清癯骨相，眉峰凌厉入鬓" if gender == "male" else "冰肌玉骨之出尘清冷相，眉若远山含黛"
        return {
            "bone_structure": bone,
            "skin_micro_texture": "温润如玉的细腻自然肤质，无凡尘杂质，真实健康光泽",
            "blemishes_and_scars": "眉心或腕间极淡的灵力胎记或陈年暗淡剑痕",
            "eye_lip_anatomy": "双眸清亮如秋水，神光内敛，薄唇微抿，神情淡漠脱俗",
            "hair_texture": "墨黑长发如瀑，以玉簪或古意缎带半束，发丝轻逸飘洒",
        }

    def get_character_costume(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        top = "素白或暗青色宽袖交领古风长袍，衣襟绣有暗纹流云饰边，带微风拂动自然褶皱" if gender == "male" else "月白轻容曳地广袖齐胸襦裙，外罩薄如蝉翼的织金纱罗，飘逸脱俗"
        bottom = "垂坠感宽腿武服褶裤，腰束云纹皮质护腰带" if gender == "male" else "同色系飘逸曳地长裙，下摆绣有暗纹花卉"
        return {
            "top_wear": top,
            "bottom_wear": bottom,
            "footwear": "鞋尖微翘的云锦薄底暗纹皂靴或软底步履，纤尘不染",
            "wear_and_tear_details": "长袍下摆微带御剑或风霜细微痕迹，内敛沉稳",
        }

    def get_character_anchor_item(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "item_name": f"{char_name}的护身灵玉/信物",
            "physical_description": "通体温润透光的羊脂白玉佩或玄铁古剑鞘，表面刻有古朴宗门禁制秘纹",
            "narrative_function": f"第{episode_num}集灵力法阵感应与宗门身份识别信物",
        }

    def get_character_psychology(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "want": f"在第{episode_num}集因果死局与正邪对立中寻得一线生机与道心突破",
            "need": "破除心魔执念，守住本心道义与庇护之人的周全",
            "lie": "唯有顺应天道斩断七情六欲方能求得大圆满",
            "ghost": "当年宗门剧变或至亲陨落留下的不可言说之旧恨",
        }

    def get_character_personality(
        self,
        char_name: str,
    ) -> str:
        return "气度高华脱俗，言行遵循天道章法，外冷内热，重诺轻生，遇剧变心坚如磐"

    def get_scene_weathering_elements(
        self,
        scene_name: str,
    ) -> tuple[str, str]:
        material = "weathered wood timber frame, mortise and tenon architecture, aged bricks, stone masonry and clay tiles"
        desc = f"{scene_name}主体榫卯木石梁柱与飞檐斗拱，带真实风吹日晒与岁月青苔包浆"
        return material, desc

    def get_hero_prop_keywords(self) -> list[str]:
        return [
            "佩剑", "玉佩", "丹药", "符箓", "拂尘", "灵石", "秘籍", "铜镜", "香炉", "乾坤袋",
            "折扇", "令牌", "卷轴", "琴谱", "药鼎", "灵珠", "法印", "古剑", "锦盒", "血玉",
        ]

    def get_anchor_prop_keywords(self) -> list[str]:
        return ["玉佩", "剑穗", "发簪", "铜钱", "扳指", "红绳", "香囊", "手串", "酒葫芦", "佩饰"]

    def get_atmospheric_prop_keywords(self) -> list[str]:
        return ["青瓷茶盏", "香炉青烟", "灯笼", "蒲团", "烛台", "石桌", "落花", "拂尘", "案几", "酒坛"]

    def get_deformation_verbs(self) -> list[str]:
        return [
            "斩断", "击碎", "焚毁", "祭出", "震裂", "消融", "封印", "崩断", "剑气洞穿", "化为飞灰",
            "撕裂", "浸染血迹", "崩口", "开裂", "捏碎", "摔在地上", "卷刃", "打翻", "震碎",
        ]

    def get_title_prefixes(self) -> list[str]:
        return [
            "宗主", "掌门", "长老", "真人", "尊上", "仙尊", "魔尊", "道友", "师尊", "堂主", "舵主",
            "盟主", "锦衣卫", "东厂", "提督", "掌柜", "大人", "刺客", "头领", "老", "小",
        ]

    def get_title_suffixes(self) -> list[str]:
        return [
            "宗主", "掌门", "长老", "真人", "仙尊", "尊上", "大人", "公公", "姑娘", "公子",
            "师傅", "总管", "师兄", "师姐", "师弟", "师妹", "道友", "前辈",
        ]

    def infer_character_gender_and_age(
        self,
        char_name: str,
        screenplay_context: str = "",
    ) -> tuple[str, int]:
        """【仙侠题材角色性别与年龄特异性推断】"""
        female_xianxia_tokens = {
            "仙子", "圣女", "师姐", "师妹", "魔女", "道姑", "神女", "姑娘", "妖姬",
            "公主", "夫人", "师尊女", "小姐", "侍女", "红颜"
        }
        if any(tok in char_name for tok in female_xianxia_tokens):
            gender = "female"
        elif any(tok in char_name for tok in ("道长", "仙尊", "魔尊", "师兄", "师弟", "真人", "剑尊", "公子", "老祖")):
            gender = "male"
        else:
            return super().infer_character_gender_and_age(char_name, screenplay_context)

        # 仙侠年龄推断
        if any(tok in char_name for tok in ("老祖", "太上", "太师祖", "尊者", "老怪")):
            age = 60
        elif any(tok in char_name for tok in ("宗主", "掌门", "长老", "真人", "仙尊", "魔尊")):
            age = 45
        elif any(tok in char_name for tok in ("弟子", "药童", "小师妹", "小师弟", "少年", "少女")):
            age = 18
        else:
            age = 26
        return gender, age
