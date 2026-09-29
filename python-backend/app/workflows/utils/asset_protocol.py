"""全剧资产四段式确定性命名与寻址协议核心工具库 (Asset Protocol Helper)。

严格遵循《AI 原创连续剧短剧工业管线标准作业程序》SKILL1.md 章节三：
资产 ID = [大类前缀] _ [对象英文标识] _ [等级/分层] _ [功能类型/状态修饰符]

1. 命名空间规范：
   - 大类前缀 (Category): CHAR_ (角色), ENV_ (场景), PROP_ (道具), VOICE_ (声音)
   - 对象英文标识 (Object Token): 阶段 2 / 阶段 3 锁定的唯一英文大写标识 (如 LINWAN, WAREHOUSE07, BLOOD_LETTER)
   - 等级分层 (Tier): T1 (一级基础/主场景/核心物证), T2 (二级表现/过渡场景/锚定物), T3 (三级专项/环境杂物)
   - 功能/状态修饰符 (Function / State): BASE_PORTRAIT, BASE_COSTUME, 4V_PROFILE, STATIC, ACTION, WIDE, OTS_BG, 等

2. 提供：
   - 解析器 (parse_asset_id)
   - 验证器 (validate_asset_id)
   - 容错规范化器 (normalize_asset_id)
   - 构造器 (build_asset_id)
   - 资产血统与底图依赖推导引擎 (resolve_asset_dependency)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# 四段式标准正则匹配模式
# 例如: CHAR_LINWAN_T1_BASE_PORTRAIT, PROP_LETTER_T1_ACTION_BURNT, VOICE_LINWAN_T1_MASTER
ASSET_ID_REGEX = re.compile(
    r"^(?P<category>CHAR|ENV|PROP|VOICE)"
    r"_(?P<token>[A-Z0-9]+)"
    r"_(?P<tier>T1|T2|T3)"
    r"_(?P<function>[A-Z0-9]+)"
    r"(?:_(?P<modifier>[A-Z0-9_]+))?$"
)

# 兼容 VOICE_<TOKEN>_MASTER 简写
VOICE_MASTER_SHORT_REGEX = re.compile(
    r"^(?P<category>VOICE)_(?P<token>[A-Z0-9]+)_(?P<function>MASTER)$"
)


@dataclass(frozen=True)
class ParsedAssetID:
    """结构化解析后的四段式资产 ID。"""
    category: str       # CHAR / ENV / PROP / VOICE
    object_token: str   # LINWAN / WAREHOUSE07 / etc.
    tier: str           # T1 / T2 / T3
    function_type: str  # BASE_PORTRAIT / STATIC / etc.
    modifier: str | None = None  # BURNT / EP45 / etc.
    raw_id: str = ""

    @property
    def standard_id(self) -> str:
        """返回标准化资产 ID 字符串。"""
        if self.modifier:
            return f"{self.category}_{self.object_token}_{self.tier}_{self.function_type}_{self.modifier}"
        return f"{self.category}_{self.object_token}_{self.tier}_{self.function_type}"


@dataclass(frozen=True)
class AssetDependency:
    """资产生成依赖与工作流参数。"""
    asset_id: str
    parent_asset_id: str | None
    generation_mode: str  # t2i / i2i / inpaint / controlnet / crop_macro / tts
    recommended_denoise: float
    workflow_note: str


class AssetProtocolHelper:
    """全剧资产四段式协议核心工具类。"""

    @classmethod
    def chinese_to_token(cls, name: str) -> str:
        """将中文或混合文本转换为纯大写英文 Token。"""
        if not name:
            return ""
        try:
            from pypinyin import lazy_pinyin  # type: ignore
            py_list = lazy_pinyin(str(name).strip())
            py_str = "".join(py_list).upper()
            clean = re.sub(r"[^A-Z0-9]", "", py_str)
            if clean:
                return clean
        except ImportError:
            pass
        clean_latin = re.sub(r"[^A-Z0-9]", "", str(name).upper())
        return clean_latin

    @classmethod
    def normalize_id(cls, raw_id: Any) -> str:
        """对输入的原始资产 ID 执行确定性纠偏与清洗。
        
        - 移除前后空白
        - 转为全大写
        - 将非英文字母数字及连字符替换为下划线
        - 压缩连续多余的下划线
        - 兼容 VOICE_<TOKEN>_MASTER 自动规范化为 VOICE_<TOKEN>_T1_MASTER
        """
        if not raw_id:
            return ""
        val = str(raw_id).strip().upper()
        val = re.sub(r"[^A-Z0-9]+", "_", val).strip("_")

        # 针对 VOICE_<TOKEN>_MASTER 形式，标准化为 VOICE_<TOKEN>_T1_MASTER
        m_voice = VOICE_MASTER_SHORT_REGEX.match(val)
        if m_voice:
            return f"VOICE_{m_voice.group('token')}_T1_MASTER"

        return val

    @classmethod
    def parse_id(cls, raw_id: Any) -> ParsedAssetID | None:
        """解析资产 ID，返回结构化 ParsedAssetID。若不合法则返回 None。"""
        normalized = cls.normalize_id(raw_id)
        if not normalized:
            return None

        m = ASSET_ID_REGEX.match(normalized)
        if not m:
            return None

        return ParsedAssetID(
            category=m.group("category"),
            object_token=m.group("token"),
            tier=m.group("tier"),
            function_type=m.group("function"),
            modifier=m.group("modifier"),
            raw_id=normalized,
        )

    @classmethod
    def validate_id(
        cls,
        raw_id: Any,
        expected_category: str | None = None,
        allowed_tokens: set[str] | None = None,
    ) -> tuple[bool, str]:
        """严格校验资产 ID 是否符合章节三四段式协议规范。
        
        :param raw_id: 待校验的资产 ID
        :param expected_category: 可选，期望的大类前缀 (CHAR / ENV / PROP / VOICE)
        :param allowed_tokens: 可选，已锁定的对象英文标识白名单集合
        :return: (is_valid, reason)
        """
        if not raw_id or not str(raw_id).strip():
            return False, "资产 ID 不能为空"

        parsed = cls.parse_id(raw_id)
        if not parsed:
            parts = str(raw_id).strip().split("_")
            cat = parts[0].upper() if parts else ""
            if cat not in ("CHAR", "ENV", "PROP", "VOICE"):
                return False, f"资产 ID '{raw_id}' 未知分类 '{cat}'"
            if len(parts) < 4 or (len(parts) >= 3 and not parts[2].startswith("T")):
                return False, f"资产 ID '{raw_id}' 格式违规：必须为4段结构 [大类]_[对象]_[等级]_[功能]"
            tier = parts[2].upper()
            if tier not in ("T1", "T2", "T3"):
                return False, f"资产 ID '{raw_id}' 梯队代码无效 '{tier}'"
            return False, (
                f"资产 ID '{raw_id}' 格式违规：必须为4段结构并符合四段式公式 "
                "[大类前缀]_[对象英文标识]_[等级分层]_[功能类型/修饰符]，例如 CHAR_LINWAN_T1_BASE_PORTRAIT"
            )

        if expected_category and parsed.category != expected_category.upper():
            return False, (
                f"资产 ID '{raw_id}' 大类前缀不符：期望为 '{expected_category.upper()}' (期望 {expected_category.upper()}_ 开头)，实际为 '{parsed.category}'"
            )

        if allowed_tokens and parsed.object_token not in allowed_tokens:
            return False, (
                f"资产 ID '{raw_id}' 对象英文标识 '{parsed.object_token}' 未在前期阶段白名单中锁定注册"
            )

        return True, "合规通过"

    @classmethod
    def build_id(
        cls,
        category: str,
        object_token: str,
        tier: str,
        function_type: str,
        modifier: str | None = None,
    ) -> str:
        """构建标准四段式资产 ID。"""
        cat = category.strip().upper()
        tok = re.sub(r"[^A-Z0-9]+", "", object_token.strip().upper())
        tr = tier.strip().upper()
        func = function_type.strip().upper()
        mod = modifier.strip().upper() if modifier else None

        if mod:
            return f"{cat}_{tok}_{tr}_{func}_{mod}"
        return f"{cat}_{tok}_{tr}_{func}"

    @classmethod
    def resolve_dependency(cls, raw_id: Any) -> AssetDependency:
        """依据章节三寻址协议推导底图依赖与推荐生图工作流参数。
        
        - 0号基准肖像 (BASE_PORTRAIT)、场景全景 (WIDE)、静态道具 (STATIC): 纯文生图 T2I
        - 基础定妆 (BASE_COSTUME): 以 BASE_PORTRAIT 为底图 I2I (Denoise 0.45)
        - 四角度视图 (4V_*): 以 BASE_COSTUME 为底图 ControlNet (Denoise 0.40)
        - 情绪图 (EXP_*): 以 BASE_PORTRAIT 为底图 Inpainting (Denoise 0.40)
        - 战损分支 (STATUS_*): 以 BASE_COSTUME 为底图 Inpainting (Denoise 0.40)
        - 物证破坏态 (ACTION*): 以 STATIC 为底图 Inpainting (Denoise 0.50)
        - 场景过肩板 (OTS_BG): 以 WIDE 为底图 Depth Blur (Denoise 0.30)
        """
        parsed = cls.parse_id(raw_id)
        if not parsed:
            return AssetDependency(
                asset_id=str(raw_id),
                parent_asset_id=None,
                generation_mode="t2i",
                recommended_denoise=1.0,
                workflow_note="非标 ID，默认回退纯文生图",
            )

        cat = parsed.category
        tok = parsed.object_token
        func = parsed.function_type
        mod = parsed.modifier or ""
        full_func = f"{func}_{mod}" if mod else func

        # 1. 角色大类 CHAR
        if cat == "CHAR":
            if full_func == "BASE_PORTRAIT" or func == "BASE_PORTRAIT":
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=1.0,
                    workflow_note="文生图 T2I 初始生成，全剧唯一 0 号人脸基因源",
                )
            elif full_func == "BASE_COSTUME" or func == "BASE_COSTUME":
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="i2i",
                    recommended_denoise=0.45,
                    workflow_note="以 BASE_PORTRAIT 为底图 I2I 扩展全身定妆",
                )
            elif func == "4V" or full_func.startswith("4V"):
                parent = f"CHAR_{tok}_T1_BASE_COSTUME"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="controlnet",
                    recommended_denoise=0.40,
                    workflow_note="以 BASE_COSTUME 为底图 ControlNet 姿态旋转",
                )
            elif func == "EXP" or full_func.startswith("EXP"):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="inpaint",
                    recommended_denoise=0.40,
                    workflow_note="以 BASE_PORTRAIT 为底图局部重绘情绪微表情",
                )
            elif func == "LIGHT" or full_func.startswith("LIGHT"):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="relighting",
                    recommended_denoise=0.35,
                    workflow_note="以 BASE_PORTRAIT 为底图 Relighting 极端光感测试",
                )
            elif func == "MACRO" or full_func.startswith("MACRO"):
                parent = f"CHAR_{tok}_T1_BASE_COSTUME"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="crop_macro",
                    recommended_denoise=0.50,
                    workflow_note="从 BASE_COSTUME 局部裁剪放大锁定微距特写",
                )
            elif func == "STATUS" or full_func.startswith("STATUS"):
                parent = f"CHAR_{tok}_T1_BASE_COSTUME"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="inpaint",
                    recommended_denoise=0.40,
                    workflow_note="以 BASE_COSTUME 为底图局部重绘战损/负伤状态",
                )

        # 2. 场景大类 ENV
        elif cat == "ENV":
            if full_func == "WIDE" or func == "WIDE":
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=1.0,
                    workflow_note="纯文生图 T2I，主场景全景建立图",
                )
            elif full_func in ("OTS_BG", "OTS") or func == "OTS":
                parent = f"ENV_{tok}_T1_WIDE"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="depth_blur",
                    recommended_denoise=0.30,
                    workflow_note="以 ENV_WIDE 为底图执行 Depth Blur 景深虚化对白背景垫图",
                )
            elif func == "INSERT" or full_func.startswith("INSERT"):
                parent = f"ENV_{tok}_T1_WIDE"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="crop_insert",
                    recommended_denoise=0.40,
                    workflow_note="从 ENV_WIDE 局部微距截取空间静物空镜",
                )
            elif func == "STATE" or func.startswith("STATE_"):
                parent = f"ENV_{tok}_T1_WIDE"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="controlnet_weather",
                    recommended_denoise=0.45,
                    workflow_note="以 ENV_WIDE 为底图 ControlNet 锁空间几何变换气候色温",
                )
            elif func == "KEYFRAME":
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=1.0,
                    workflow_note="纯文生图 T2I，次要过渡场景单张关键帧",
                )

        # 3. 道具大类 PROP
        elif cat == "PROP":
            if func == "STATIC":
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=1.0,
                    workflow_note="纯文生图 T2I，核心物证完整静态初始态",
                )
            elif func == "ACTION" or func.startswith("ACTION_"):
                parent = f"PROP_{tok}_T1_STATIC"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="inpaint",
                    recommended_denoise=0.50,
                    workflow_note="以 PROP_STATIC 为底图 Inpainting 局部重绘物理破坏交互态",
                )

        # 4. 声音大类 VOICE
        elif cat == "VOICE":
            return AssetDependency(
                asset_id=parsed.standard_id,
                parent_asset_id=None,
                generation_mode="tts_master",
                recommended_denoise=0.0,
                workflow_note="抓取高光金句 + 1:1 翻译阶段 2 腔体人设生成的母音频",
            )

        # 默认回退
        return AssetDependency(
            asset_id=parsed.standard_id,
            parent_asset_id=None,
            generation_mode="t2i",
            recommended_denoise=1.0,
            workflow_note="通用资产生成",
        )
