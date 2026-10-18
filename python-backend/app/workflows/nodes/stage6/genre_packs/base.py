"""题材预设包基础抽象类与协议接口 (Genre Pack Base Interface)。

本模块定义了多题材自适应架构的核心协议 `BaseGenrePack`。
支持不同题材（如悬疑、仙侠古装、科幻废土、都市言情等）动态注入：
  - 角色生理特征 (bio_dna)
  - 角色着装规范 (costume_specs)
  - 随身信物与心理四维 (carried_anchor_item / psychology_4)
  - 空间场景风化做旧规格 (scene_weathering)
  - 核心高频物证关键词与破坏动词 (props & verbs)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.logger import get_logger

logger = get_logger("lmd.stage6.genre_pack")


class BaseGenrePack(ABC):
    """【规则编号: RULE-GENRE-PACK-BASE】题材预设包基础抽象类。

    所有特定题材（如悬疑、仙侠、科幻、都市）均须继承此类并实现其抽象方法。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """题材唯一英文标识符（如 'suspense', 'xianxia', 'scifi', 'urban_romance'）。"""
        pass

    @property
    @abstractmethod
    def label(self) -> str:
        """题材中文显示名称（如 '现代悬疑/犯罪', '古装玄幻/仙侠'）。"""
        pass

    @property
    @abstractmethod
    def match_keywords(self) -> list[str]:
        """用于匹配剧本题材的关键词列表。"""
        pass

    def matches(self, text: str) -> bool:
        """判断给定的题材文本、视觉风格或剧本文本是否匹配本题材包。"""
        if not text:
            return False
        lower_t = text.lower()
        return any(kw.lower() in lower_t for kw in self.match_keywords)

    @abstractmethod
    def get_character_bio(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        """获取角色的生理骨相与皮肤微观细节。"""
        pass

    @abstractmethod
    def get_character_costume(
        self,
        char_name: str,
        gender: str,
        perceived_age: int,
    ) -> dict[str, str]:
        """获取角色的生活化服装规格（包含上装、下装、鞋履、磨损细节）。"""
        pass

    @abstractmethod
    def get_character_anchor_item(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        """获取角色的随身信物与交互锚点。"""
        pass

    @abstractmethod
    def get_character_psychology(
        self,
        char_name: str,
        episode_num: int,
    ) -> dict[str, str]:
        """获取角色的心理四维设定（want, need, lie, ghost）。"""
        pass

    @abstractmethod
    def get_character_personality(
        self,
        char_name: str,
    ) -> str:
        """获取角色的通用性格底色描述。"""
        pass

    @abstractmethod
    def get_scene_weathering_elements(
        self,
        scene_name: str,
    ) -> tuple[str, str]:
        """获取场景的主体材质与结构描述 (struct_material, struct_desc)。"""
        pass

    @abstractmethod
    def get_hero_prop_keywords(self) -> list[str]:
        """获取本题材下的一级剧情核心物证关键词列表。"""
        pass

    @abstractmethod
    def get_anchor_prop_keywords(self) -> list[str]:
        """获取本题材下的随身锚点小物件关键词列表。"""
        pass

    @abstractmethod
    def get_atmospheric_prop_keywords(self) -> list[str]:
        """获取本题材下的环境氛围小道具关键词列表。"""
        pass

    @abstractmethod
    def get_deformation_verbs(self) -> list[str]:
        """获取本题材下的破坏形变动作动词列表。"""
        pass

    def get_title_prefixes(self) -> list[str]:
        """获取本题材下常见的角色职务/前缀称谓列表（用于别名归一化与代词消歧剥离）。"""
        return ["老", "小", "阿"]

    def get_title_suffixes(self) -> list[str]:
        """获取本题材下常见的角色尊称/后缀称谓列表（用于别名归一化与代词消歧剥离）。"""
        return ["哥", "姐", "叔", "伯", "姨", "先生", "女士"]

    def infer_character_gender_and_age(
        self,
        char_name: str,
        screenplay_context: str = "",
    ) -> tuple[str, int]:
        """【题材自适应角色性别与年龄智能推断】

        职责说明：
            当上游阶段（LLM 阶段 6 提示词抽取）未直接标明角色性别或预估年龄时，
            本方法作为第三级题材兜底，结合角色名称特定字词、前后文语境与题材专属文化语境，
            平滑推断出最合理的生物学生理性别 ('male'|'female') 与视听生理年龄。

        Args:
            char_name (str): 角色实体名称（如 '周老四', '苏仙子', '李处长'）。
            screenplay_context (str): 角色登场出现位置的剧本上下文段落（可选，用于代词共现核验）。

        Returns:
            tuple[str, int]: 包含推断性别与预估年龄的二元组，如 ("male", 45)。
        """
        # 1. 第一步：尝试从剧本上下文段落统计第三人称代词（'她' vs '他'）
        detected_gender = ""
        if screenplay_context:
            she_cnt = screenplay_context.count("她")
            he_cnt = screenplay_context.count("他")
            if she_cnt > he_cnt:
                detected_gender = "female"
                logger.debug(
                    "【题材包推断】角色 [%s] 剧本上下文代词命中: 她(%d) > 他(%d) -> 性别判定为 female",
                    char_name, she_cnt, he_cnt
                )
            elif he_cnt > she_cnt:
                detected_gender = "male"
                logger.debug(
                    "【题材包推断】角色 [%s] 剧本上下文代词命中: 他(%d) > 她(%d) -> 性别判定为 male",
                    char_name, he_cnt, she_cnt
                )

        # 2. 第二步：若上下文代词无明显偏向，依据通用中文尊称与称谓推断性别
        if not detected_gender:
            female_tokens = {
                "姐", "妹", "娘", "姑", "母", "姨", "婆", "女", "妃", "后",
                "夫人", "小姐", "女士", "太太", "千金", "妇", "姥", "奶"
            }
            male_tokens = {
                "哥", "弟", "爷", "叔", "伯", "父", "公", "汉", "郎", "王",
                "皇", "少爷", "先生", "汉子", "老汉", "壮士", "四", "三", "二", "大"
            }
            if any(tok in char_name for tok in female_tokens):
                detected_gender = "female"
            elif any(tok in char_name for tok in male_tokens):
                detected_gender = "male"
            else:
                detected_gender = "male"  # 工业底模中立默认男中音基准

        # 3. 第三步：推断视听生理年龄（依据中文字缀辈分与职衔特征）
        if any(tok in char_name for tok in ("老", "爷", "伯", "叔", "婆", "太", "翁", "公")):
            inferred_age = 48
        elif any(tok in char_name for tok in ("总", "董", "长", "掌门", "长老", "官", "捕头", "师傅")):
            inferred_age = 40
        elif any(tok in char_name for tok in ("小", "妹", "弟", "生", "少爷", "小姐", "弟子", "侍女", "童")):
            inferred_age = 22
        elif any(tok in char_name for tok in ("哥", "姐", "嫂")):
            inferred_age = 32
        else:
            inferred_age = 28

        logger.debug(
            "【题材包推断完成】题材包 [%s] 角色 [%s] -> 推断性别: %s, 预估年龄: %d",
            self.name, char_name, detected_gender, inferred_age
        )
        return detected_gender, inferred_age
