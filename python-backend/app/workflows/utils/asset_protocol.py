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

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# 四段式标准正则匹配模式
# 例如: CHAR_LINWAN_T1_BASE_PORTRAIT, PROP_LETTER_T1_ACTION_BURNT, VOICE_LINWAN_T1_MASTER
# 兼容场景子区域 Z01 / 道具形态 S0 等结构化层级标识
ASSET_ID_REGEX = re.compile(
    r"^(?P<category>CHAR|ENV|PROP|VOICE)"
    r"_(?P<token>[A-Z0-9]+)"
    r"_(?P<tier>T[1-3]|Z\d+|S\d+)"
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
    tier: str           # T1 / T2 / T3 / Z01 / S0
    function_type: str  # BASE_PORTRAIT / STATIC / etc.
    modifier: str | None = None  # BURNT / EP45 / etc.
    raw_id: str = ""

    @property
    def standard_id(self) -> str:
        """返回标准化资产 ID 字符串。"""
        if self.modifier:
            return f"{self.category}_{self.object_token}_{self.tier}_{self.function_type}_{self.modifier}"
        return f"{self.category}_{self.object_token}_{self.tier}_{self.function_type}"

    @property
    def token(self) -> str:
        """对象令牌别名 (与 object_token 等价)。"""
        return self.object_token

    @property
    def function(self) -> str:
        """功能类型别名 (与 function_type 等价)。"""
        return self.function_type


@dataclass(frozen=True)
class AssetDependency:
    """资产生成依赖与工作流参数。"""
    asset_id: str
    parent_asset_id: str | None
    generation_mode: str  # t2i / i2i / inpaint / controlnet / crop_macro / tts / depth_blur
    recommended_denoise: float
    workflow_note: str
    control_type: str | None = None
    is_benchmark: int = 0

    @property
    def parent_asset_key(self) -> str | None:
        """别名：父资产唯一编码。"""
        return self.parent_asset_id

    @property
    def denoise_strength(self) -> float:
        """别名：推荐重绘降噪度。"""
        return self.recommended_denoise


# 确定性依赖推导规则注册表 (DAG Lineage Rules)
DEPENDENCY_RULES: dict[str, dict[str, Any]] = {
    # 角色类
    "BASE_PORTRAIT": {
        "generation_mode": "t2i",
        "recommended_denoise": 0.0,
        "control_type": None,
        "parent_suffix": None,
        "is_benchmark": 1,
        "note": "文生图 T2I 初始生成，全剧唯一 0 号人脸基因源基准",
    },
    "BASE_COSTUME": {
        "generation_mode": "i2i",
        "recommended_denoise": 0.45,
        "control_type": None,
        "parent_suffix": "BASE_PORTRAIT",
        "is_benchmark": 0,
        "note": "以 BASE_PORTRAIT 为底图 I2I 扩展全身定妆",
    },
    "4V_FRONT": {
        "generation_mode": "controlnet",
        "recommended_denoise": 0.40,
        "control_type": "openpose",
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "以 BASE_COSTUME 为底图 ControlNet OpenPose 姿态约束",
    },
    "4V_SIDE": {
        "generation_mode": "controlnet",
        "recommended_denoise": 0.40,
        "control_type": "openpose",
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "以 BASE_COSTUME 为底图 ControlNet OpenPose 侧面约束",
    },
    "4V_BACK": {
        "generation_mode": "controlnet",
        "recommended_denoise": 0.40,
        "control_type": "openpose",
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "以 BASE_COSTUME 为底图 ControlNet OpenPose 背面约束",
    },
    "4V_THREE_QUARTER": {
        "generation_mode": "controlnet",
        "recommended_denoise": 0.40,
        "control_type": "openpose",
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "以 BASE_COSTUME 为底图 ControlNet OpenPose 3/4 侧身约束",
    },
    "4V_3Q": {
        "generation_mode": "controlnet",
        "recommended_denoise": 0.40,
        "control_type": "openpose",
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "以 BASE_COSTUME 为底图 ControlNet OpenPose 3/4 侧身约束",
    },
    "EXP": {
        "generation_mode": "inpaint",
        "recommended_denoise": 0.38,
        "control_type": "inpaint_face",
        "parent_suffix": "BASE_PORTRAIT",
        "is_benchmark": 0,
        "note": "以 BASE_PORTRAIT 为底图局部重绘情绪微表情",
    },
    "LIGHT": {
        "generation_mode": "relighting",
        "recommended_denoise": 0.35,
        "control_type": None,
        "parent_suffix": "BASE_PORTRAIT",
        "is_benchmark": 0,
        "note": "以 BASE_PORTRAIT 为底图 Relighting 光感测试",
    },
    "MACRO": {
        "generation_mode": "crop_macro",
        "recommended_denoise": 0.50,
        "control_type": None,
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "从 BASE_COSTUME 局部裁剪放大锁定微距特写",
    },
    "MACRO_FACE": {
        "generation_mode": "crop_macro",
        "recommended_denoise": 0.50,
        "control_type": None,
        "parent_suffix": "BASE_PORTRAIT",
        "is_benchmark": 0,
        "note": "从 BASE_PORTRAIT 局部裁剪放大锁定面部五官超清微距",
    },
    "MACRO_HAND": {
        "generation_mode": "crop_macro",
        "recommended_denoise": 0.50,
        "control_type": None,
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "从 BASE_COSTUME 局部裁剪放大锁定手部微距特写",
    },
    "STATUS": {
        "generation_mode": "inpaint",
        "recommended_denoise": 0.40,
        "control_type": "inpaint_status",
        "parent_suffix": "BASE_COSTUME",
        "is_benchmark": 0,
        "note": "以 BASE_COSTUME 为底图局部重绘战损/负伤状态",
    },
    # 场景类
    "WIDE": {
        "generation_mode": "t2i",
        "recommended_denoise": 0.0,
        "control_type": None,
        "parent_suffix": None,
        "is_benchmark": 1,
        "note": "纯文生图 T2I，主场景全景超广角空镜基准图",
    },
    "OTS_BG": {
        "generation_mode": "depth_blur",
        "recommended_denoise": 0.30,
        "control_type": "depth",
        "parent_suffix": "WIDE",
        "is_benchmark": 0,
        "note": "以 ENV_WIDE 为底图执行 Depth Blur 景深虚化对白背景垫图",
    },
    "STATE": {
        "generation_mode": "controlnet_weather",
        "recommended_denoise": 0.45,
        "control_type": "lineart",
        "parent_suffix": "WIDE",
        "is_benchmark": 0,
        "note": "以 ENV_WIDE 为底图 ControlNet 锁空间几何变换气候色温",
    },
    "INSERT": {
        "generation_mode": "crop_insert",
        "recommended_denoise": 0.40,
        "control_type": None,
        "parent_suffix": "WIDE",
        "is_benchmark": 0,
        "note": "从 ENV_WIDE 局部微距截取空间静物空镜",
    },
    # 道具类
    "STATIC": {
        "generation_mode": "t2i",
        "recommended_denoise": 0.0,
        "control_type": None,
        "parent_suffix": None,
        "is_benchmark": 1,
        "note": "纯文生图 T2I，核心物证完整静态初始基准态",
    },
    "ACTION": {
        "generation_mode": "inpaint",
        "recommended_denoise": 0.50,
        "control_type": "inpaint_only",
        "parent_suffix": "STATIC",
        "is_benchmark": 0,
        "note": "以 PROP_STATIC 为底图 Inpainting 局部重绘物理破坏交互态",
    },
    # 声音类
    "MASTER": {
        "generation_mode": "tts_master",
        "recommended_denoise": 0.0,
        "control_type": None,
        "parent_suffix": None,
        "is_benchmark": 1,
        "note": "抓取高光金句 + 腔体人设生成的母音频",
    },
}


class AssetProtocolHelper:
    """全剧资产四段式协议核心工具类。"""

    @classmethod
    def chinese_to_token(cls, name: str) -> str:
        """将中文或混合文本转换为纯大写英文/数字 Token（符合 [A-Z0-9]+ 正则约束）。

        优先使用 pypinyin 转写全大写拼音；若当前运行环境未安装 pypinyin，
        则使用确定性 MD5 十六进制指纹混合已有拉丁字符生成纯 [A-Z0-9] 标识，
        确保在任何环境下生成的 Token 均 100% 通过 ASSET_ID_REGEX 四段式校验。
        """
        if not name:
            return ""
        raw_str = str(name).strip()
        try:
            from pypinyin import lazy_pinyin  # type: ignore
            py_list = lazy_pinyin(raw_str)
            py_str = "".join(py_list).upper()
            clean = re.sub(r"[^A-Z0-9]", "", py_str)
            if clean:
                return clean
        except ImportError:
            pass
        clean_latin = re.sub(r"[^A-Z0-9]", "", raw_str.upper())
        if clean_latin:
            return clean_latin
        # 无 pypinyin 且纯中文输入时：使用确定性哈希生成纯大写字母数字 Token (如 CN8F3A2B1C)
        if re.search(r"[\u4e00-\u9fff]", raw_str):
            import hashlib
            digest = hashlib.md5(raw_str.encode("utf-8")).hexdigest()[:8].upper()
            return f"CN{digest}"
        return ""

    @classmethod
    def normalize_id(cls, raw_id: Any) -> str:
        """对输入的原始资产 ID 执行确定性纠偏与清洗。
        
        - 移除前后空白
        - 转为全大写
        - 将非英文字母数字及连字符替换为下划线
        - 压缩连续多余的下划线
        - 兼容 VOICE_<TOKEN>_MASTER 自动规范化为 VOICE_<TOKEN>_T1_MASTER
        - 兼容常见非标阶段变体纠偏：如 STAGE_1 / STAGE1 纠偏为 T1，STAGE_2 / STAGE2 纠偏为 T2 等
        """
        if not raw_id:
            return ""
        val = str(raw_id).strip().upper()
        val = re.sub(r"[^A-Z0-9]+", "_", val).strip("_")

        # 兼容常见阶段非标拼写
        val = re.sub(r"_STAGE_?1_", "_T1_", val)
        val = re.sub(r"_STAGE_?2_", "_T2_", val)
        val = re.sub(r"_STAGE_?3_", "_T3_", val)

        # 针对 VOICE_<TOKEN>_MASTER 形式，标准化为 VOICE_<TOKEN>_T1_MASTER
        m_voice = VOICE_MASTER_SHORT_REGEX.match(val)
        if m_voice:
            return f"VOICE_{m_voice.group('token')}_T1_MASTER"

        # 针对角色三段式 CHAR_<TOKEN>_T1_BASE 自动规范化为四段式 CHAR_<TOKEN>_T1_BASE_PORTRAIT
        # 严格保证全剧 0 号基准肖像四段式命名 SSOT 单一真理源
        if re.match(r"^CHAR_[A-Z0-9]+_T1_BASE$", val):
            return f"{val}_PORTRAIT"

        return val

    @classmethod
    def sanitize_scene_location(cls, raw_location: Any) -> str:
        """从剧本标头或非标文本中清洗提取纯粹的物理地点名称。

        剥离场景头编号、内景/外景、日夜气候、时间光线及上游切片后缀，
        确保返回的是物理空间单一真理名称（如 '苏秀兰旧居灵堂'）。
        """
        if not raw_location:
            return ""
        s = str(raw_location).strip()

        # 1. 剥离场次序号（如 【场景 01】、第1场、场1-1、1-1、1-01、1.1、1、等）
        s = re.sub(r"^【?\s*(?:场景|场次|场|第\s*\d+\s*[场幕])\s*\d*(?:[-_—–\.]\d+)?\s*】?[\s:：]*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"^\d+[-_—–\.]\d+[\.、\s]*", "", s)
        s = re.sub(r"^\d+[\.、]\s*", "", s)

        # 2. 剥离环境与时间修饰头（如 日 内、夜 外、日/内、内外、内景、外景、日景、夜景、室内、室外）
        for _ in range(3):
            s = re.sub(r"^(?:内景|外景|室内|室外|日景|夜景|[日夜晚晨昏内外])[\.·\s\-_/]*", "", s, flags=re.IGNORECASE).strip()

        # 3. 按连字符或分隔符切分（如果是 '地点 - 时间/氛围'，取地点主干）
        parts = re.split(r"\s*[-—–｜|/]\s*", s)
        if len(parts) > 1:
            first = parts[0].strip()
            if any('\u4e00' <= char <= '\u9fff' for char in first) and len(first) >= 2:
                s = first

        # 4. 剥离括号内的修饰词（如 (深夜)、（暴雨））
        s = re.sub(r"[（(][^）)]*[）)]", "", s).strip()

        # 5. 剥离上游或保底切片后缀（如 -核心区域、-空间结构基准、-主活动区、-活动区、-全景基准）
        s = re.sub(r"[_\-—–](?:核心区域|空间结构基准|主活动区|活动区|全景基准|宏观特写|微距特写)$", "", s).strip()

        # 6. 剥离残存的环境前缀与时间尾缀
        for _ in range(2):
            s = re.sub(r"^(?:内景|外景|室内|室外|[日夜晚晨昏内外])[\.·\s\-_/]*", "", s, flags=re.IGNORECASE).strip()
        s = re.sub(r"[\s\-_]*(?:深夜|清晨|黎明|黄昏|白昼|暴雨|大雨|雨夜|雪夜|阴天|晴天|日|夜)$", "", s).strip()

        return s or str(raw_location).strip()

    @classmethod
    def normalize_token(cls, raw_token: Any) -> str:
        """规范化提取资产 token 标识，支持中文转拼音大写并去除类别前缀。"""
        if not raw_token:
            return "DEFAULT"
        # 尝试执行场景纯名清洗，避免非标标头带入杂质
        cleaned = cls.sanitize_scene_location(raw_token)
        s = str(cleaned or raw_token).strip()
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in s)
        if has_chinese:
            tok = cls.chinese_to_token(s)
        else:
            tok = re.sub(r'[^A-Za-z0-9_]', '', s).upper()
        # 去除可能存在的类别前缀
        for pfx in ("CHAR_", "ENV_", "PROP_", "VOICE_"):
            if tok.startswith(pfx):
                tok = tok[len(pfx):]
                break
        return tok.strip("_") or "DEFAULT"

    @classmethod
    def generate_deterministic_id(
        cls,
        category: str,
        name: str,
        form_tag: str = "T1_BASE",
    ) -> str:
        """跨集跨次生成绝对不变的确定性四段式资产 ID。
        
        保证同一名称和形态在任何集数、任何环境多次运行，生成的资产 ID 100% 字节级一致。
        
        :param category: 大类前缀 (CHAR / ENV / PROP / VOICE)
        :param name: 实体名称 (如 "沈炼", "红星轧钢厂筒子楼", "腰牌")
        :param form_tag: 派生形态标识 (如 "T1_BASE", "T3_STATUS_INJURED", "Z01_ZONE", "S0_STATIC", "S1_ACTION")
        :return: 规范的四段式标准 ID
        """
        cat = category.strip().upper()
        if cat not in ("CHAR", "ENV", "PROP", "VOICE"):
            cat = "CHAR"

        token = cls.chinese_to_token(name)
        if not token:
            token = "UNKNOWN"

        clean_form = form_tag.strip().upper().replace("-", "_")

        # 1. 角色分类 (CHAR)
        if cat == "CHAR":
            if "INJURED" in clean_form or "STATUS" in clean_form or "COMBAT" in clean_form:
                tier = "T3"
                func = "STATUS_INJURED"
            elif "MACRO" in clean_form or "HAND" in clean_form:
                tier = "T3"
                func = "MACRO_HAND"
            elif "COSTUME" in clean_form or "4V" in clean_form:
                tier = "T1"
                func = "BASE_COSTUME"
            else:
                tier = "T1"
                func = "BASE_PORTRAIT"
            return f"CHAR_{token}_{tier}_{func}"

        # 2. 场景分类 (ENV)
        elif cat == "ENV":
            if "ZONE" in clean_form or "Z0" in clean_form:
                tier = "Z01"
                func = "ZONE"
            elif "OTS" in clean_form:
                tier = "T1"
                func = "OTS_BG"
            else:
                tier = "T1"
                func = "WIDE"
            return f"ENV_{token}_{tier}_{func}"

        # 3. 道具分类 (PROP)
        elif cat == "PROP":
            if "ACTION" in clean_form or "DAMAGED" in clean_form or "S1" in clean_form:
                tier = "T1"
                func = "ACTION"
            else:
                tier = "T1"
                func = "STATIC"
            return f"PROP_{token}_{tier}_{func}"

        # 4. 声音母音 (VOICE)
        else:
            return f"VOICE_{token}_T1_MASTER"

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
            if len(parts) < 4 or (len(parts) >= 3 and not (parts[2].startswith("T") or parts[2].startswith("Z") or parts[2].startswith("S"))):
                return False, f"资产 ID '{raw_id}' 格式违规：必须为4段结构 [大类]_[对象]_[等级]_[功能]"
            tier = parts[2].upper()
            if not re.match(r"^(T[1-3]|Z\d+|S\d+)$", tier):
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
    def _fuzzy_resolve_non_standard(cls, raw_id: Any) -> AssetDependency:
        """针对非标准资产 ID 执行启发式自愈与防降级推导。
        
        【设计目标】:
        当模型生成或外部传入非标 ID (如 CHAR_LUCHEN_STAGE2_PORTRAIT, PROP_SWORD_S2_STATIC 等) 时，
        绝不能盲目将其回退为文生图 (t2i)，必须通过正则与语义推断其类别与梯队，
        将 Tier 2 / Tier 3 资产自愈并锚定到对应 Tier 1 祖先基准图上。
        """
        raw_str = str(raw_id or "").strip().upper()
        norm_str = cls.normalize_id(raw_str)

        # 1. 尝试识别类别
        cat = None
        for cand_cat in ("CHAR", "ENV", "PROP", "VOICE"):
            if norm_str.startswith(f"{cand_cat}_"):
                cat = cand_cat
                break

        # 2. 尝试识别梯队 (Tier)
        tier = "T1"
        m_tier = re.search(r"_(T[1-3]|Z\d+|S\d+)_", norm_str)
        if m_tier:
            tier = m_tier.group(1)
        elif "_STAGE_?2" in norm_str or "_T2" in norm_str or "_2_" in norm_str:
            tier = "T2"
        elif "_STAGE_?3" in norm_str or "_T3" in norm_str or "_3_" in norm_str:
            tier = "T3"

        # 3. 尝试提取对象 token
        tok = "DEFAULT"
        if cat:
            rem = norm_str[len(cat) + 1:]
            parts = rem.split("_")
            if parts and parts[0]:
                tok = re.sub(r"[^A-Z0-9]+", "", parts[0]) or "DEFAULT"

        # 4. 根据推断结果进行防降级自愈
        if cat == "CHAR":
            if tier in ("T2", "T3"):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                logger.warning(
                    "【资产寻址协议·非标自愈·防降级】角色非标 ID [%s] 识别为 Tier %s，强制挂载 T1 基准肖像 [%s] 进行 i2i 衍生，拦截 t2i 人脸漂移！",
                    raw_id, tier, parent,
                )
                return AssetDependency(
                    asset_id=norm_str or str(raw_id),
                    parent_asset_id=parent,
                    generation_mode="i2i",
                    recommended_denoise=0.35,
                    workflow_note=f"非标 ID 自愈引擎：识别为角色 {tier} 阶段资产，挂载 T1 基准肖像图生图",
                    control_type=None,
                    is_benchmark=0,
                )
            else:
                # T1 角色非标资产
                if any(k in norm_str for k in ("COSTUME", "FULL_BODY", "FULLBODY", "BODY")):
                    parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                    return AssetDependency(
                        asset_id=norm_str or str(raw_id),
                        parent_asset_id=parent,
                        generation_mode="i2i",
                        recommended_denoise=0.45,
                        workflow_note="非标 ID 自愈：T1 服饰图生图",
                        control_type=None,
                        is_benchmark=0,
                    )
                logger.debug("【资产寻址协议·非标自愈】角色 T1 肖像资产 [%s] 判定为基准根节点", raw_id)
                return AssetDependency(
                    asset_id=norm_str or str(raw_id),
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=0.0,
                    workflow_note="非标 ID 自愈：角色 T1 初始基准肖像",
                    control_type=None,
                    is_benchmark=1,
                )

        elif cat == "ENV":
            if tier in ("T2", "T3") or str(tier).startswith("Z02") or str(tier).startswith("Z2"):
                parent = f"ENV_{tok}_T1_WIDE"
                logger.warning(
                    "【资产寻址协议·非标自愈·防降级】场景非标 ID [%s] 识别为 Tier %s，强制挂载 T1 主全景 [%s] 进行 i2i 衍生，拦截 t2i！",
                    raw_id, tier, parent,
                )
                return AssetDependency(
                    asset_id=norm_str or str(raw_id),
                    parent_asset_id=parent,
                    generation_mode="i2i",
                    recommended_denoise=0.45,
                    workflow_note=f"非标 ID 自愈引擎：识别为场景 {tier} 过渡/气候衍生，挂载主场景全景图生图",
                    control_type="lineart",
                    is_benchmark=0,
                )
            else:
                return AssetDependency(
                    asset_id=norm_str or str(raw_id),
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=0.0,
                    workflow_note="非标 ID 自愈：主场景全景基准图",
                    control_type=None,
                    is_benchmark=1,
                )

        elif cat == "PROP":
            if tier in ("T2", "T3") or str(tier).startswith("S2") or str(tier).startswith("S02") or str(tier).startswith("S3"):
                parent = f"PROP_{tok}_T1_STATIC"
                logger.warning(
                    "【资产寻址协议·非标自愈·防降级】道具非标 ID [%s] 识别为 Tier %s，强制挂载 T1 静态基准 [%s] 进行 i2i 衍生，拦截 t2i！",
                    raw_id, tier, parent,
                )
                return AssetDependency(
                    asset_id=norm_str or str(raw_id),
                    parent_asset_id=parent,
                    generation_mode="i2i",
                    recommended_denoise=0.45,
                    workflow_note=f"非标 ID 自愈引擎：识别为道具 {tier} 演化态，挂载初始静态基准图生图",
                    control_type=None,
                    is_benchmark=0,
                )
            else:
                return AssetDependency(
                    asset_id=norm_str or str(raw_id),
                    parent_asset_id=None,
                    generation_mode="t2i",
                    recommended_denoise=0.0,
                    workflow_note="非标 ID 自愈：核心物证初始静态基准图",
                    control_type=None,
                    is_benchmark=1,
                )

        elif cat == "VOICE":
            return AssetDependency(
                asset_id=norm_str or str(raw_id),
                parent_asset_id=None,
                generation_mode="tts_master",
                recommended_denoise=0.0,
                workflow_note="非标 ID 自愈：声音母音资产",
                control_type=None,
                is_benchmark=1,
            )

        # 无法推断类别的兜底
        logger.warning("【资产寻址协议·未知非标ID】无法解析类别与梯队的资产 ID [%s]，默认安全回退", raw_id)
        return AssetDependency(
            asset_id=str(raw_id),
            parent_asset_id=None,
            generation_mode="t2i",
            recommended_denoise=1.0,
            workflow_note="未知非标 ID，默认回退纯文生图",
            control_type=None,
            is_benchmark=0,
        )

    @classmethod
    def resolve_dependency(cls, raw_id: Any) -> AssetDependency:
        """依据章节三寻址协议推导底图依赖与推荐生图工作流参数。
        
        【防降级核心原则 (Anti-Degradation Core Rules)】:
        1. 仅 Tier 1 / Level 0 初始根基准（0号肖像基准 BASE_PORTRAIT、主全景 WIDE、初始完好静态道具 STATIC、母音频 MASTER）允许使用文生图 (t2i)，无父级，is_benchmark=1；
        2. 所有 Tier 2 / Tier 3 及演化分支资产（分阶段定妆、换装、战损、四视角、微表情、局部破坏等）坚决禁止使用文生图 (t2i)，必须通过图生图 (i2i)、局部重绘 (inpaint)、姿态控制 (controlnet) 继承自对应 Tier 1 祖先基准，is_benchmark=0；
        3. 非标 ID 自动执行启发式自愈，纠偏分类、实体与等级，严格规避静默降级为 t2i。
        """
        parsed = cls.parse_id(raw_id)
        if not parsed:
            return cls._fuzzy_resolve_non_standard(raw_id)

        cat = parsed.category
        tok = parsed.object_token
        tier = parsed.tier
        func = parsed.function_type
        mod = parsed.modifier or ""
        full_func = f"{func}_{mod}" if mod else func

        # 1. 角色大类 CHAR
        if cat == "CHAR":
            if full_func in ("BASE_PORTRAIT", "MAIN_PORTRAIT", "PORTRAIT", "BASE") or (not mod and func in ("BASE_PORTRAIT", "MAIN_PORTRAIT", "PORTRAIT", "BASE")):
                # 只有 T1 0号基准肖像才允许使用文生图作为全剧人脸基因源；
                # T2 / T3 分阶段肖像 (换装/进阶/战损/成长) 必须通过图生图继承自 T1 肖像，严防人脸特征崩塌！
                if tier == "T1":
                    logger.debug("【资产寻址协议·基准肖像锁定】角色 [%s] T1 基准肖像锁定为文生图根节点 (t2i, parent=None, is_benchmark=1)", parsed.standard_id)
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=None,
                        generation_mode="t2i",
                        recommended_denoise=0.0,
                        workflow_note="文生图 T2I 初始生成，全剧唯一 0 号人脸基因源基准",
                        control_type=None,
                        is_benchmark=1,
                    )
                else:
                    parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                    logger.debug(
                        "【资产寻址协议·阶段肖像防降级】角色 [%s] 阶段 %s 肖像锁定为图生图，继承自 T1 基准肖像 [%s] (i2i, denoise=0.35)",
                        parsed.standard_id, tier, parent,
                    )
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=parent,
                        generation_mode="i2i",
                        recommended_denoise=0.35,
                        workflow_note=f"以 T1 初始基准肖像为底图 I2I 迁移面部特征，保持阶段 {tier} 定妆与全剧角色面相一致性",
                        control_type=None,
                        is_benchmark=0,
                    )
            elif full_func in ("BASE_COSTUME", "FULL_BODY", "FULLBODY", "COSTUME") or func in ("BASE_COSTUME", "FULL_BODY", "COSTUME"):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="i2i",
                    recommended_denoise=0.45,
                    workflow_note="以 BASE_PORTRAIT 为底图 I2I 扩展全身定妆",
                    control_type=None,
                    is_benchmark=0,
                )
            elif func == "4V" or full_func.startswith("4V") or func in ("FRONT", "SIDE", "BACK", "3Q", "PROFILE") or full_func in ("4V_SHEET", "FOUR_VIEW"):
                parent = f"CHAR_{tok}_T1_BASE_COSTUME"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="controlnet",
                    recommended_denoise=0.40,
                    workflow_note="以 BASE_COSTUME 为底图 ControlNet 姿态约束",
                    control_type="openpose",
                    is_benchmark=0,
                )
            elif func == "EXP" or full_func.startswith("EXP"):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="inpaint",
                    recommended_denoise=0.38,
                    workflow_note="以 BASE_PORTRAIT 为底图局部重绘情绪微表情",
                    control_type="inpaint_face",
                    is_benchmark=0,
                )
            elif func == "LIGHT" or full_func.startswith("LIGHT"):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="relighting",
                    recommended_denoise=0.35,
                    workflow_note="以 BASE_PORTRAIT 为底图 Relighting 极端光感测试",
                    control_type=None,
                    is_benchmark=0,
                )
            elif full_func in ("MACRO_FACE", "MACRO_FACIAL") or (func == "MACRO" and mod in ("FACE", "FACIAL")):
                parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="crop_macro",
                    recommended_denoise=0.50,
                    workflow_note="从 BASE_PORTRAIT 局部裁剪放大锁定面部五官超清微距",
                    control_type=None,
                    is_benchmark=0,
                )
            elif func == "MACRO" or full_func.startswith("MACRO"):
                parent = f"CHAR_{tok}_T1_BASE_COSTUME"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="crop_macro",
                    recommended_denoise=0.50,
                    workflow_note="从 BASE_COSTUME 局部裁剪放大锁定微距特写",
                    control_type=None,
                    is_benchmark=0,
                )
            elif func == "STATUS" or full_func.startswith("STATUS"):
                parent = f"CHAR_{tok}_T1_BASE_COSTUME"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="inpaint",
                    recommended_denoise=0.40,
                    workflow_note="以 BASE_COSTUME 为底图局部重绘战损/负伤状态",
                    control_type="inpaint_status",
                    is_benchmark=0,
                )

        # 2. 场景大类 ENV
        elif cat == "ENV":
            if full_func == "WIDE" or func == "WIDE":
                # 只有 T1 / Z01 主场景全景空镜允许纯文生图；次级场景、气候变体或子区域全景必须挂载主全景进行图生图
                if tier in ("T1", "Z01", "Z1"):
                    logger.debug("【资产寻址协议·主场景全景锁定】场景 [%s] 锁定为主全景文生图基准 (t2i, parent=None, is_benchmark=1)", parsed.standard_id)
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=None,
                        generation_mode="t2i",
                        recommended_denoise=0.0,
                        workflow_note="纯文生图 T2I，主场景全景超广角空镜基准图",
                        control_type=None,
                        is_benchmark=1,
                    )
                else:
                    parent = f"ENV_{tok}_T1_WIDE" if tier.startswith("T") else f"ENV_{tok}_Z01_WIDE"
                    logger.debug(
                        "【资产寻址协议·次级场景防降级】场景 [%s] (Tier=%s) 锁定为图生图，继承自主全景 [%s] (i2i, denoise=0.45)",
                        parsed.standard_id, tier, parent,
                    )
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=parent,
                        generation_mode="i2i",
                        recommended_denoise=0.45,
                        workflow_note=f"以 {parent} 为底图衍生过渡场景或气候变换全景，严防降级为文生图",
                        control_type="lineart",
                        is_benchmark=0,
                    )
            elif full_func in ("OTS_BG", "OTS") or func == "OTS":
                parent_tier = tier if tier.startswith("Z") else "T1"
                parent = f"ENV_{tok}_{parent_tier}_WIDE"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="depth_blur",
                    recommended_denoise=0.30,
                    workflow_note="以 ENV_WIDE 为底图执行 Depth Blur 景深虚化对白背景垫图",
                    control_type="depth",
                    is_benchmark=0,
                )
            elif func == "INSERT" or full_func.startswith("INSERT"):
                parent_tier = tier if tier.startswith("Z") else "T1"
                parent = f"ENV_{tok}_{parent_tier}_WIDE"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="crop_insert",
                    recommended_denoise=0.40,
                    workflow_note="从 ENV_WIDE 局部微距截取空间静物空镜",
                    control_type=None,
                    is_benchmark=0,
                )
            elif func == "STATE" or func.startswith("STATE_"):
                parent_tier = tier if tier.startswith("Z") else "T1"
                parent = f"ENV_{tok}_{parent_tier}_WIDE"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="controlnet_weather",
                    recommended_denoise=0.45,
                    workflow_note="以 ENV_WIDE 为底图 ControlNet 锁空间几何变换气候色温",
                    control_type="lineart",
                    is_benchmark=0,
                )
            elif func == "KEYFRAME":
                if tier in ("T1", "Z01", "Z1"):
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=None,
                        generation_mode="t2i",
                        recommended_denoise=0.0,
                        workflow_note="纯文生图 T2I，次要过渡场景单张关键帧",
                        control_type=None,
                        is_benchmark=0,
                    )
                else:
                    parent = f"ENV_{tok}_T1_WIDE" if tier.startswith("T") else f"ENV_{tok}_Z01_WIDE"
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=parent,
                        generation_mode="i2i",
                        recommended_denoise=0.45,
                        workflow_note=f"以 {parent} 为底图衍生过渡场景关键帧，防降级",
                        control_type=None,
                        is_benchmark=0,
                    )

        # 3. 道具大类 PROP
        elif cat == "PROP":
            if func == "STATIC" or full_func == "STATIC":
                # 只有 T1 / S0 初始完好道具态允许纯文生图；次级演化态、破损形态必须挂载初始静态基准进行图生图
                if tier in ("T1", "S0"):
                    logger.debug("【资产寻址协议·道具初始基准锁定】道具 [%s] 锁定为静态基准态 (t2i, parent=None, is_benchmark=1)", parsed.standard_id)
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=None,
                        generation_mode="t2i",
                        recommended_denoise=0.0,
                        workflow_note="纯文生图 T2I，核心物证完整静态初始基准态",
                        control_type=None,
                        is_benchmark=1,
                    )
                else:
                    parent = f"PROP_{tok}_T1_STATIC" if tier.startswith("T") else f"PROP_{tok}_S0_STATIC"
                    logger.debug(
                        "【资产寻址协议·道具演化防降级】道具 [%s] (Tier=%s) 锁定为图生图，继承自初始静态基准 [%s] (i2i, denoise=0.45)",
                        parsed.standard_id, tier, parent,
                    )
                    return AssetDependency(
                        asset_id=parsed.standard_id,
                        parent_asset_id=parent,
                        generation_mode="i2i",
                        recommended_denoise=0.45,
                        workflow_note=f"以 {parent} 静态基准态为底图进行演化态衍生，严防降级为文生图",
                        control_type=None,
                        is_benchmark=0,
                    )
            elif func == "ACTION" or func.startswith("ACTION_") or "DAMAGED" in full_func or "BURNT" in full_func:
                parent_tier = tier if tier.startswith("S") else "T1"
                parent = f"PROP_{tok}_{parent_tier}_STATIC"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="inpaint",
                    recommended_denoise=0.50,
                    workflow_note="以 PROP_STATIC 为底图 Inpainting 局部重绘物理破坏交互态",
                    control_type="inpaint_only",
                    is_benchmark=0,
                )
            elif func == "DETAIL" or full_func.startswith("DETAIL"):
                parent_tier = tier if tier.startswith("S") else "T1"
                parent = f"PROP_{tok}_{parent_tier}_STATIC"
                return AssetDependency(
                    asset_id=parsed.standard_id,
                    parent_asset_id=parent,
                    generation_mode="crop_macro",
                    recommended_denoise=0.45,
                    workflow_note="从 PROP_STATIC 局部裁剪放大锁定核心特征细节",
                    control_type=None,
                    is_benchmark=0,
                )

        # 4. 声音大类 VOICE
        elif cat == "VOICE":
            return AssetDependency(
                asset_id=parsed.standard_id,
                parent_asset_id=None,
                generation_mode="tts_master",
                recommended_denoise=0.0,
                workflow_note="抓取高光金句 + 1:1 翻译阶段 2 腔体人设生成的母音频",
                control_type=None,
                is_benchmark=1,
            )

        # 兜底：若属于 Tier 2 或 Tier 3，绝对禁止回退为 t2i
        if tier in ("T2", "T3"):
            safe_parent = None
            if cat == "CHAR":
                safe_parent = f"CHAR_{tok}_T1_BASE_PORTRAIT"
            elif cat == "ENV":
                safe_parent = f"ENV_{tok}_T1_WIDE"
            elif cat == "PROP":
                safe_parent = f"PROP_{tok}_T1_STATIC"
            logger.warning(
                "【资产寻址协议·兜底防降级】资产 [%s] (Tier=%s) 命中未定义功能，强制转换为图生图模式并挂载祖先基准 [%s]",
                parsed.standard_id, tier, safe_parent,
            )
            return AssetDependency(
                asset_id=parsed.standard_id,
                parent_asset_id=safe_parent,
                generation_mode="i2i",
                recommended_denoise=0.45,
                workflow_note=f"以 {safe_parent or '祖先基准'} 为底图进行通用图生图衍生",
                control_type=None,
                is_benchmark=0,
            )

        # 默认回退（仅非 T2/T3 未知资产）
        return AssetDependency(
            asset_id=parsed.standard_id,
            parent_asset_id=None,
            generation_mode="t2i",
            recommended_denoise=1.0,
            workflow_note="通用资产生成",
            control_type=None,
            is_benchmark=0,
        )

    @classmethod
    def get_dependency_rule(cls, raw_id: Any) -> AssetDependency:
        """别名：推导资产依赖规则。"""
        return cls.resolve_dependency(raw_id)

    VIEW_TYPE_TO_CHAR_FUNCTION: dict[str, str] = {
        "BASE": "BASE_PORTRAIT",
        "T1_BASE": "BASE_PORTRAIT",
        "MAIN_PORTRAIT": "BASE_PORTRAIT",
        "PORTRAIT": "BASE_PORTRAIT",
        "BASE_PORTRAIT": "BASE_PORTRAIT",
        "FULL_BODY": "BASE_COSTUME",
        "FULLBODY": "BASE_COSTUME",
        "COSTUME": "BASE_COSTUME",
        "BASE_COSTUME": "BASE_COSTUME",
        "FRONT_VIEW": "4V_FRONT",
        "FRONT": "4V_FRONT",
        "4V_FRONT": "4V_FRONT",
        "4V_FRONT_FULL": "4V_FRONT",
        "SIDE_VIEW": "4V_SIDE",
        "SIDE": "4V_SIDE",
        "PROFILE": "4V_SIDE",
        "4V_SIDE": "4V_SIDE",
        "4V_PROFILE": "4V_SIDE",
        "BACK_VIEW": "4V_BACK",
        "BACK": "4V_BACK",
        "REAR": "4V_BACK",
        "4V_BACK": "4V_BACK",
        "THREE_QUARTER_VIEW": "4V_3Q",
        "THREE_QUARTER": "4V_3Q",
        "3Q": "4V_3Q",
        "4V_3Q": "4V_3Q",
        "4V_THREE_QUARTER": "4V_3Q",
        "FOUR_VIEW": "4V_SHEET",
        "4V_SHEET": "4V_SHEET",
        "SHEET": "4V_SHEET",
        "FACIAL_MACRO": "MACRO_FACE",
        "MACRO_FACE": "MACRO_FACE",
        "HANDS_DETAIL": "MACRO_HAND",
        "MACRO_HAND": "MACRO_HAND",
        "DETAIL": "DETAIL_SLICE",
        "DETAIL_SLICE": "DETAIL_SLICE",
        "EXP": "EXP",
        "EXPRESSION": "EXP",
        "STATUS_INJURED": "STATUS_INJURED",
        "LIGHT_FLASH": "LIGHT_FLASH",
        "LIGHT_LOWKEY": "LIGHT_LOWKEY",
    }

    VIEW_TYPE_TO_SCENE_FUNCTION: dict[str, str] = {
        "WIDE": "WIDE",
        "PANORAMA": "WIDE",
        "MAIN": "WIDE",
        "OTS_BG": "OTS_BG",
        "OTS": "OTS_BG",
        "STATE": "STATE",
        "WEATHER": "STATE",
        "EPISODE_WEATHERING": "STATE",
        "INSERT": "INSERT",
        "MACRO": "INSERT",
    }

    VIEW_TYPE_TO_PROP_FUNCTION: dict[str, str] = {
        "STATIC": "STATIC",
        "PRISTINE": "STATIC",
        "ACTION": "ACTION",
        "DAMAGED": "ACTION",
        "DETAIL": "DETAIL",
        "MACRO_FEATURE": "DETAIL",
    }

    @classmethod
    def build_character_asset_key(
        cls,
        token: str,
        stage_code: str = "T1",
        view_type: str = "BASE_PORTRAIT",
    ) -> str:
        """构建角色层级标准资产 Key。"""
        tok = cls.normalize_token(token)
        stg = stage_code.strip().upper()
        if not stg.startswith("T") and stg.isdigit():
            stg = f"T{stg}"
        elif not stg.startswith("T") and stg in ("BASE", "DEFAULT", "ORIGIN"):
            stg = "T1"
        raw_vt = view_type.strip().upper()
        vt = cls.VIEW_TYPE_TO_CHAR_FUNCTION.get(raw_vt, raw_vt)
        return f"CHAR_{tok}_{stg}_{vt}"

    @classmethod
    def build_scene_asset_key(
        cls,
        token: str,
        zone_code: str = "Z01",
        view_type: str = "WIDE",
    ) -> str:
        """构建场景层级标准资产 Key。"""
        tok = cls.normalize_token(token)
        zn = zone_code.strip().upper()
        raw_vt = view_type.strip().upper()
        vt = cls.VIEW_TYPE_TO_SCENE_FUNCTION.get(raw_vt, raw_vt)
        return f"ENV_{tok}_{zn}_{vt}"

    @classmethod
    def build_prop_asset_key(
        cls,
        token: str,
        state_code: str = "S0",
        view_type: str = "STATIC",
    ) -> str:
        """构建道具层级标准资产 Key。"""
        tok = cls.normalize_token(token)
        st = state_code.strip().upper()
        raw_vt = view_type.strip().upper()
        vt = cls.VIEW_TYPE_TO_PROP_FUNCTION.get(raw_vt, raw_vt)
        return f"PROP_{tok}_{st}_{vt}"

    @classmethod
    def build_benchmark_asset_key(
        cls,
        category: str,
        name_or_token: str,
        stage_or_zone: str = "T1",
    ) -> str:
        """构建各类资产类别的真理源基准 Key。"""
        cat = category.strip().lower()
        if cat in ("character", "char"):
            return cls.build_character_asset_key(name_or_token, stage_code=stage_or_zone, view_type="BASE_PORTRAIT")
        elif cat in ("scene", "environment", "env"):
            zn = stage_or_zone if stage_or_zone.startswith("Z") else f"Z{stage_or_zone}"
            return cls.build_scene_asset_key(name_or_token, zone_code=zn, view_type="WIDE")
        elif cat in ("prop",):
            st = stage_or_zone if stage_or_zone.startswith("S") else f"S{stage_or_zone}"
            return cls.build_prop_asset_key(name_or_token, state_code=st, view_type="STATIC")
        elif cat in ("voice", "audio"):
            return f"VOICE_{cls.normalize_token(name_or_token)}_{stage_or_zone.upper()}_MASTER"
        return f"ASSET_{cls.normalize_token(name_or_token)}_BENCHMARK"

    @classmethod
    def get_benchmark_key_for_character(cls, token: str, stage_code: str = "T1") -> str:
        """获取角色的 0 号人脸基准资产 Key (CHAR_<TOKEN>_<STAGE>_BASE_PORTRAIT)。"""
        return cls.build_character_asset_key(token, stage_code, "BASE_PORTRAIT")

    @classmethod
    def get_benchmark_key_for_scene(cls, token: str, zone_code: str = "Z01") -> str:
        """获取场景的主空间基准全景资产 Key (ENV_<TOKEN>_<ZONE>_WIDE)。"""
        return cls.build_scene_asset_key(token, zone_code, "WIDE")

    @classmethod
    def get_benchmark_key_for_prop(cls, token: str, state_code: str = "S0") -> str:
        """获取道具的完好初始基准资产 Key (PROP_<TOKEN>_<STATE>_STATIC)。"""
        return cls.build_prop_asset_key(token, state_code, "STATIC")
