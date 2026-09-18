"""复合时序单镜整秒时长倒逼与自适应拆镜算子 (Shot Duration Calculator)。

【规则编号: RULE-V-S7-02】严格遵循 SKILL1.md v10.0.0 阶段 7 核心时序硬核工业标准：
- 复合时长计算公式：T_total = T_action + T_prop + (dialogue_len / speed + 0.3s) + 0.4s
- 整秒向上锁定：T_total <= 6.5s 强制锁定为 [2.0, 7.0]s 闭区间内的整秒数
- 自动解耦拆镜：T_total > 6.5s 强制拆解为：
    - 镜头 A (动作铺垫镜)：2.0s ~ 3.0s 整秒，纯动作、静音或无对白；
    - 镜头 B (对白特写镜)：4.0s ~ 7.0s 整秒，入点呼吸留白 0.3s，容纳完整对白
- 全集总时长 ±6.0s 容差硬核校验
- 毫秒级时间码转换

100% 纯代码确定性逻辑，严禁大模型介入决策。
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("lmd.shot_duration_calculator")

# 业务常数与阈值配置
DEFAULT_SPEECH_SPEED = 4.5
FAST_SPEECH_SPEED = 5.0
PRE_SPEECH_INHALE_SEC = 0.3
POST_SPEECH_BUFFER_SEC = 0.4

MIN_SHOT_DURATION_SEC = 2.0
MAX_SINGLE_SHOT_LIMIT_SEC = 7.0
SPLIT_THRESHOLD_SEC = 6.5


def clean_dialogue_text(raw_text: str | None) -> str:
    """清洗对白文本，去除括号内提示与多余符号，仅统计纯文本字符长度。"""
    if not raw_text:
        return ""
    cleaned = re.sub(r"[\uff08\uff09\(\)][^\uff09\)]*[\uff09\)]", "", str(raw_text))
    cleaned = re.sub(r"（[^）]+）|\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5]", "", cleaned)
    return cleaned.strip()


def format_timecode_ms(total_seconds: float) -> str:
    """毫秒级精确 SRT 时间码格式化 (00:01:23,456)。"""
    sec_float = max(0.0, float(total_seconds))
    hours = int(sec_float // 3600)
    minutes = int((sec_float % 3600) // 60)
    secs = int(sec_float % 60)
    ms = int(round((sec_float - int(sec_float)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_timecode_range(start_sec: float, duration_sec: float) -> str:
    """生成标准字幕起止时间码区间 (00:00:00,000 --> 00:00:02,500)。"""
    end_sec = start_sec + duration_sec
    return f"{format_timecode_ms(start_sec)} --> {format_timecode_ms(end_sec)}"


@dataclass
class SingleShotPlan:
    """计算拆分后的单镜设计方案。"""
    shot_tag: str
    duration_sec: float
    speech_inpoint_sec: float | None
    has_dialogue: bool
    is_dialogue_complete_in_shot: bool
    recommended_framing: str
    rationale: str

    def to_shot_dict(self, shot_id: int = 1) -> dict[str, Any]:
        """转换为标准 StoryboardShot 字典。"""
        return {
            "shot_id": shot_id,
            "duration_sec": self.duration_sec,
            "rationale": self.rationale,
            "audio": {
                "voice_type": "dialogue" if self.has_dialogue else None,
                "speech_inpoint_sec": self.speech_inpoint_sec,
                "is_dialogue_complete_in_shot": self.is_dialogue_complete_in_shot,
            },
            "recommended_framing": self.recommended_framing,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_shot_dict().get(key)


@dataclass
class ShotDurationResult:
    """复合时长计算与解耦拆镜输出结果。"""
    raw_total_sec: float
    is_split: bool
    split_decision_reason: str
    plans: list[SingleShotPlan] = field(default_factory=list)

    @property
    def total_duration_sec(self) -> float:
        return sum(p.duration_sec for p in self.plans)

    @property
    def shots(self) -> list[dict[str, Any]]:
        return [p.to_shot_dict(i + 1) for i, p in enumerate(self.plans)]


def calculate_shot_duration(
    dialogue_text: str | None = None,
    action_complexity: Literal["none", "light", "medium", "heavy"] = "light",
    prop_interaction: Literal["none", "touch", "complex_deformation"] = "none",
    speech_speed: float = DEFAULT_SPEECH_SPEED,
    custom_action_sec: float | None = None,
    custom_prop_sec: float | None = None,
    *,
    action_desc: str | None = None,
    prop_desc: str | None = None,
    is_fast_pace: bool = False,
) -> ShotDurationResult:
    """【规则编号: RULE-V-S7-02】执行复合时序倒逼与整秒锁定/强制拆镜算子。"""
    eff_speed = FAST_SPEECH_SPEED if is_fast_pace else speech_speed

    # 文本启发式推导复杂度
    if action_desc and custom_action_sec is None:
        if len(action_desc) > 20 or any(k in action_desc for k in ["逼近", "打斗", "奔跑", "搏杀", "撕裂", "争夺"]):
            action_complexity = "medium"
        elif len(action_desc) > 0:
            action_complexity = "light"
        else:
            action_complexity = "none"

    if prop_desc and custom_prop_sec is None:
        if any(k in prop_desc for k in ["撕", "碎", "点燃", "砸碎", "划过", "摩擦"]):
            prop_interaction = "complex_deformation"
        elif len(prop_desc) > 0:
            prop_interaction = "touch"
        else:
            prop_interaction = "none"

    # 1. 基础动作时长 T_action
    if custom_action_sec is not None:
        t_action = max(0.0, float(custom_action_sec))
    else:
        if action_complexity == "none":
            t_action = 0.0
        elif action_complexity == "light":
            t_action = 0.8
        elif action_complexity == "medium":
            t_action = 1.4
        else:
            t_action = 2.0

    # 2. 道具交互时长 T_prop
    if custom_prop_sec is not None:
        t_prop = max(0.0, float(custom_prop_sec))
    else:
        if prop_interaction == "none":
            t_prop = 0.0
        elif prop_interaction == "touch":
            t_prop = 0.6
        else:
            t_prop = 1.2

    # 3. 对白时长计算
    clean_text = clean_dialogue_text(dialogue_text)
    char_count = len(clean_text)
    speed = max(1.0, float(eff_speed))

    if char_count > 0:
        speech_pure_sec = char_count / speed
        t_speech_total = speech_pure_sec + PRE_SPEECH_INHALE_SEC + POST_SPEECH_BUFFER_SEC
        has_dialogue = True
    else:
        speech_pure_sec = 0.0
        t_speech_total = 0.0
        has_dialogue = False

    t_raw_total = t_action + t_prop + t_speech_total

    # 4. 拆镜决策与整秒向上锁定
    if t_raw_total <= SPLIT_THRESHOLD_SEC:
        duration_int = math.ceil(t_raw_total)
        final_duration = float(max(MIN_SHOT_DURATION_SEC, min(MAX_SINGLE_SHOT_LIMIT_SEC, float(duration_int))))
        speech_inpoint = 0.3 if has_dialogue else None

        rationale = (
            f"基础动作({t_action:.1f}s) + 道具交互({t_prop:.1f}s) + "
            f"对白{char_count}字({speech_pure_sec:.1f}s) = {t_raw_total:.2f}s "
            f"-> 向上取整锁为 {final_duration:.1f}s"
        )
        plan = SingleShotPlan(
            shot_tag="SHOT_SINGLE",
            duration_sec=final_duration,
            speech_inpoint_sec=speech_inpoint,
            has_dialogue=has_dialogue,
            is_dialogue_complete_in_shot=True,
            recommended_framing="MCU 中近景" if has_dialogue else "CU 特写",
            rationale=rationale,
        )
        return ShotDurationResult(
            raw_total_sec=round(t_raw_total, 2),
            is_split=False,
            split_decision_reason="复合总时长 <= 6.5s，单镜容纳",
            plans=[plan],
        )
    else:
        reason = f"复合总时长 {t_raw_total:.2f}s > 6.5s 物理上限，强制解耦拆镜"
        action_part = t_action + t_prop
        duration_a = float(max(2.0, min(3.0, float(math.ceil(action_part)))))
        plan_a = SingleShotPlan(
            shot_tag="SHOT_A_ACTION",
            duration_sec=duration_a,
            speech_inpoint_sec=None,
            has_dialogue=False,
            is_dialogue_complete_in_shot=True,
            recommended_framing="CU 动作铺垫特写",
            rationale=f"【动作铺垫镜】消化前置动作({t_action:.1f}s)与道具交互({t_prop:.1f}s)，锁定为 {duration_a:.1f}s",
        )

        speech_part = speech_pure_sec + PRE_SPEECH_INHALE_SEC + POST_SPEECH_BUFFER_SEC
        duration_b = float(max(2.0, min(MAX_SINGLE_SHOT_LIMIT_SEC, float(math.ceil(speech_part)))))
        plan_b = SingleShotPlan(
            shot_tag="SHOT_B_DIALOGUE",
            duration_sec=duration_b,
            speech_inpoint_sec=0.3,
            has_dialogue=True,
            is_dialogue_complete_in_shot=True,
            recommended_framing="MCU 对白特写",
            rationale=f"【对白特写镜】容纳完整对白{char_count}字，预留0.3s留白，锁定为 {duration_b:.1f}s",
        )
        return ShotDurationResult(
            raw_total_sec=round(t_raw_total, 2),
            is_split=True,
            split_decision_reason=reason,
            plans=[plan_a, plan_b],
        )


def check_episode_duration_tolerance(
    actual_duration_sec: float | None = None,
    planned_duration_sec: float = 120.0,
    tolerance_sec: float = 6.0,
    *,
    shots_durations: list[float] | None = None,
    target_duration_sec: float | None = None,
) -> tuple[bool, float, float]:
    """【规则编号: RULE-V-S7-02】全集总时长 ±6.0s 容差校验。"""
    if shots_durations is not None:
        actual_duration_sec = sum(shots_durations)
    if target_duration_sec is not None:
        planned_duration_sec = target_duration_sec

    actual = round(float(actual_duration_sec or 0.0), 2)
    plan = round(float(planned_duration_sec), 2)
    diff = round(actual - plan, 2)
    abs_diff = abs(diff)

    is_valid = abs_diff <= tolerance_sec
    return is_valid, actual, diff


class ShotDurationCalculator:
    """镜头整秒时长倒逼与自适应拆镜算子类门面。"""
    calculate = staticmethod(calculate_shot_duration)
    check_tolerance = staticmethod(check_episode_duration_tolerance)
    format_ms = staticmethod(format_timecode_ms)
    format_range = staticmethod(format_timecode_range)

