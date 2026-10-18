"""未来科幻/赛博朋克题材预设包 (Sci-Fi & Cyberpunk Genre Pack)。

适用于未来、科幻、末日、废土、赛博朋克、星际探索等题材。
提供模块化战术夹克、神经接口、钛合金微芯片、冷凝水与霓虹合金光效。
"""
from __future__ import annotations

from app.workflows.nodes.stage6.genre_packs.base import BaseGenrePack


class SciFiGenrePack(BaseGenrePack):
    """未来科幻/赛博朋克题材预设包。"""

    @property
    def name(self) -> str:
        return "scifi"

    @property
    def label(self) -> str:
        return "未来科幻/赛博朋克/废土"

    @property
    def match_keywords(self) -> list[str]:
        return [
            "科幻", "赛博", "未来", "末世", "废土", "星际", "太空", "仿生", "人工智能", "外骨骼",
            "机械", "赛博朋克", "异星", "量子", "飞船", "机甲", "殖民", "矩阵", "纳米", "智脑",
        ]

    def get_character_bio(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        bone = "高折叠度硬朗下颌与利落对称骨相，神情冷峻专注" if gender == "male" else "清冷精致线条与分明面部折角，眼神犀利警觉"
        return {
            "bone_structure": bone,
            "skin_micro_texture": "健康细腻表皮肌理，太阳穴与耳后隐约可见淡蓝或冷白微光皮下微电路",
            "blemishes_and_scars": "耳后微型神经接口插槽或浅淡工业激光焊接吻合线",
            "eye_lip_anatomy": "虹膜带微弱数码变焦光环，目光如精密仪器般沉着，唇线平直",
            "hair_texture": "利落利索的抗静电合成纤维短发或紧扎发束，冷灰/纯黑色调",
        }

    def get_character_costume(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        return {
            "top_wear": "哑光深灰高分子纳米防风战术夹克，双肩配有轻量化外骨骼磁吸挂载点",
            "bottom_wear": "耐磨复合凯夫拉工装战术长裤，膝部加固防冲撞模块",
            "footwear": "防穿刺高抓地力磁吸多功能战术短靴，步履轻盈稳健",
            "wear_and_tear_details": "外壳边缘有细微等离子灼烧与工业摩擦痕迹，接缝密闭紧固",
        }

    def get_character_anchor_item(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "item_name": f"{char_name}的神经加密芯片",
            "physical_description": "带有纳米散热阵列与呼吸蓝光LED的钛合金数据存储芯片",
            "narrative_function": f"第{episode_num}集核心防火墙权限认证与加密日志提取介质",
        }

    def get_character_psychology(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        return {
            "want": f"在第{episode_num}集机械巨构与算力围捕中提取核心数据并脱离封锁区",
            "need": "捍卫仅存的真实血肉记忆与人性温存，抵抗算法冷酷同化",
            "lie": "纯粹的逻辑计算与冷酷理性才是永不犯错的生存法则",
            "ghost": "曾经目睹亲历的意识数据被强制抹除与同胞被重置的阴霾",
        }

    def get_character_personality(
        self,
        char_name: str,
    ) -> str:
        return "思维极度敏捷，反应精确迅猛，习惯以概率和数据评估局势，少言多行"

    def get_scene_weathering_elements(
        self,
        scene_name: str,
    ) -> tuple[str, str]:
        material = "titanium alloy panels, weathered composite carbon fiber, reinforced concrete, optical glass"
        desc = f"{scene_name}主体承重防辐射合金装甲与通风冷凝构件，带有工业管线与微弱全息光斑"
        return material, desc

    def get_hero_prop_keywords(self) -> list[str]:
        return [
            "数据芯片", "神经接入线", "光刃", "脉冲枪", "便携终端", "能量块", "注射器", "机械臂",
            "解码器", "外骨骼核心", "战术目镜", "生物采样瓶", "电磁手雷", "全息投影仪", "密钥卡",
        ]

    def get_anchor_prop_keywords(self) -> list[str]:
        return ["数据卡", "战术目镜", "战术手套", "识别牌", "挂坠芯片", "金属火机", "耳麦", "能量条"]

    def get_atmospheric_prop_keywords(self) -> list[str]:
        return ["冷凝水珠", "全息投影杂讯", "霓虹灯管", "金属废料", "营养液软管", "通风口白气", "机箱指示灯"]

    def get_deformation_verbs(self) -> list[str]:
        return [
            "熔断", "击穿", "过载短路", "捏碎", "切开", "引爆", "数据清除", "撕裂", "粉碎", "砸烂",
            "开裂", "灼烧", "强行拔出", "折断", "射穿",
        ]

    def get_title_prefixes(self) -> list[str]:
        return ["指挥官", "长官", "特工", "博士", "研究员", "工程师", "队长", "舰长", "老", "小"]

    def get_title_suffixes(self) -> list[str]:
        return ["长官", "指挥官", "博士", "研究员", "工程师", "舰长", "队长", "老兄"]
