# -*- coding: utf-8 -*-
"""文学剧本、物理连续性与钩子契约。

本模块属于短剧工作流核心状态机契约子领域。
"""
from __future__ import annotations

import logging
import operator
from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("app.schemas.states.screenplay")

from app.schemas.states.audit import StageAuditReport


class EpisodeScriptV2(BaseModel):
    """阶段 5：单集纯文学剧本标准化契约 (ep_XX.json)。"""
    episode_number: int = Field(..., description="集数编号")
    title: str = Field(default="", description="单集剧名")
    duration_seconds: float = Field(default=120.0, description="单集规划时长秒数")
    safety_guardrails_lock: dict[str, Any] = Field(
        default_factory=dict,
        description="事前三道安全护栏锁（潜台词交锋矩阵/物理摩擦力与现实代价/强因果逻辑分集任务）"
    )
    previous_episode_physical_pickup: dict[str, Any] | None = Field(
        default=None,
        description="接力前一集集尾断点的物理快照（角色体态/手持道具/环境状态）"
    )
    scenes: list[dict[str, Any]] = Field(default_factory=list, description="场次列表（纯文学剧本场次与对白）")
    dramatic_rhythm_check: dict[str, str] = Field(
        default_factory=dict,
        description="戏剧节奏自检（前3s钩子、40-60s微反转、集尾绝杀断点）"
    )
    episode_end_physical_delta: dict[str, str] = Field(
        default_factory=dict,
        description="集尾绝杀断点0秒物理快照（下一集开篇第一秒接力源）"
    )


class SeasonOutlineCard(BaseModel):
    """【单集任务卡】全季分集宏观节律任务卡（完整承载 Stage 4 双螺旋工笔契约，包含双螺旋事件链、反转钩子与潜台词矩阵）。"""
    model_config = ConfigDict(extra="allow")
    episode_number: int = Field(default=1, description="集数编号 (1..NN)")
    episode_id: int = Field(default=1, description="集数 ID (同 episode_number)")
    title: str = Field(default="", description="单集爆款标题")
    killer_title: str = Field(default="", description="商业吸睛片名")
    core_conflict_task: str = Field(default="", description="本集核心戏剧冲突任务")
    hook_cliffhanger: str = Field(default="", description="集尾 115 秒黄金悬念钩子")
    dramatic_arc_unit: str = Field(default="", description="所属戏剧微弧单元")
    # 双螺旋工笔任务卡与视听节律核心字段（全面对齐 Stage 4 交付标准与 Stage 5 执行契约）
    dual_helix_task: dict[str, Any] = Field(default_factory=dict, description="双螺旋任务卡对象（含 plot_event_chain, relational_shift_point, lie_erosion_metric）")
    subtext_matrix: dict[str, Any] = Field(default_factory=dict, description="潜台词与深层冲突矩阵")
    hook_3s: str = Field(default="", description="开篇 3 秒视觉/动作钩子")
    micro_twist_45s: str = Field(default="", description="45 秒微反转或关系质变")
    cliffhanger_end: str = Field(default="", description="集尾悬念/卡点钩子")
    raw_outline_card: dict[str, Any] = Field(default_factory=dict, description="Stage 4 生成的原始完整大纲卡片备份")

    @model_validator(mode="before")
    @classmethod
    def _normalize_outline_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            # 1. 兼容多版本集数主键别名
            ep_num = values.get("episode_number") or values.get("episode_num") or values.get("episode_id") or values.get("episode") or 1
            values["episode_number"] = int(ep_num)
            values["episode_id"] = int(ep_num)

            # 2. 标题别名对齐
            if not values.get("title") and values.get("episode_title"):
                values["title"] = str(values["episode_title"])
            if not values.get("killer_title") and values.get("title"):
                values["killer_title"] = str(values["title"])

            # 3. 节律钩子别名对齐
            if not values.get("hook_3s") and values.get("three_second_hook"):
                values["hook_3s"] = str(values["three_second_hook"])
            if not values.get("micro_twist_45s") and values.get("micro_turning_point_45s"):
                values["micro_twist_45s"] = str(values["micro_turning_point_45s"])
            if not values.get("cliffhanger_end"):
                values["cliffhanger_end"] = str(
                    values.get("killer_cliffhanger_115s")
                    or values.get("hook_cliffhanger")
                    or values.get("cliffhanger")
                    or ""
                )

            # 4. 核心任务别名对齐
            if not values.get("core_conflict_task"):
                values["core_conflict_task"] = str(
                    values.get("core_dramatic_task")
                    or values.get("task")
                    or ""
                )

            # 5. 双螺旋任务结构自动聚合（兼容扁平化字段）
            dh = values.get("dual_helix_task")
            if not isinstance(dh, dict):
                dh = {}
            if "plot_event_chain" not in dh and values.get("plot_event_chain"):
                dh["plot_event_chain"] = values["plot_event_chain"]
            if "relational_shift_point" not in dh and values.get("relational_shift_point"):
                dh["relational_shift_point"] = values["relational_shift_point"]
            if "lie_erosion_metric" not in dh and values.get("lie_erosion_metric"):
                dh["lie_erosion_metric"] = values["lie_erosion_metric"]
            values["dual_helix_task"] = dh
        return values

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        if self.__pydantic_extra__ and item in self.__pydantic_extra__:
            return self.__pydantic_extra__[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            val = self[item]
            return val if val is not None else default
        except KeyError:
            return default

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return hasattr(self, item) or (self.__pydantic_extra__ is not None and item in self.__pydantic_extra__)


class InterEpisodePhysicalContinuity(BaseModel):
    """【跨集连续性】集间 0 秒物理咬合连续性快照。"""
    model_config = ConfigDict(extra="allow")
    from_episode: int = Field(default=0, description="来源集数编号")
    to_episode: int = Field(default=0, description="目标继承集数编号")
    episode_number: int = Field(default=0, description="兼容别名：集数编号")
    character_physical_states: dict[str, str] = Field(
        default_factory=dict,
        description="角色身体姿态与肉体伤情描述 (如 {'CHAR_LUCHEN': '左肩渗血，单膝跪地'})"
    )
    prop_custody_states: dict[str, str] = Field(
        default_factory=dict,
        description="关键道具持有与损坏状态 (如 {'PROP_BLADE': '掉落右侧地面 3 米处'})"
    )
    environmental_state: str = Field(default="", description="残留环境与天气光影状态 (如 '暴雨停歇，地面积水倒映霓虹')")
    timeline_progress_sec: float = Field(default=120.0, description="前集剧情结束时的累积时间线进度秒数")

    @model_validator(mode="before")
    @classmethod
    def _sync_ep_numbers(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ep = data.get("episode_number") or data.get("from_episode") or 0
            if "from_episode" not in data or not data.get("from_episode"):
                data["from_episode"] = ep
            if "episode_number" not in data or not data.get("episode_number"):
                data["episode_number"] = ep
        return data

    def __getitem__(self, item: str) -> Any:
        if item == "episode_number":
            return getattr(self, "episode_number", 0) or self.from_episode
        if hasattr(self, item):
            return getattr(self, item)
        if self.__pydantic_extra__ and item in self.__pydantic_extra__:
            return self.__pydantic_extra__[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            val = self[item]
            return val if val is not None else default
        except KeyError:
            return default

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return hasattr(self, item) or (self.__pydantic_extra__ is not None and item in self.__pydantic_extra__)


class PreviousEpisodePickup(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】0 秒接棒物理快照字典 (第 2 集及之后强制包含)。"""
    inherited_from_episode: int
    pickup_state_description: str
    # 兼容别名
    freeze_frame_desc: str
    episode_index: int


class GoldenCliffhangerHook(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】结尾黄金悬念钩子三位一体字典。"""
    physical_crisis_action: str
    cliffhanger_dialogue: str
    acoustic_drop_cue: str
    # 兼容别名
    hook_action: str
    hook_dialogue: str
    hook_audio_braam: str


class EpisodeEndPhysicalDelta(TypedDict, total=False):
    """【规则编号: RULE-II-02 / RULE-VI-05】集尾物理状态快照字典 (封存最后一秒真实物理残局)。"""
    timeline_progress: str
    character_pose: str
    held_props_and_injuries: str
    environment_and_weather: str
    # 兼容别名
    timeline_progress_sec: float
    posture_and_injuries: str
    carried_props_status: str
    weather_and_light: str
    freeze_frame_desc: str
    location: str
    last_scene: str
    episode_index: int


class LiteraryScreenplayEpisode(TypedDict, total=False):
    """【规则编号: RULE-VI-05】阶段 5 标准单集文学剧本 (episodes_screenplay/ep_XX.json)。"""
    episode_id: int
    episode_title: str
    planned_duration_sec: float
    dramatic_arc_unit: str
    core_dramatic_task: str
    previous_episode_0s_pickup: PreviousEpisodePickup | None
    screenplay_text: str
    golden_cliffhanger_hook: GoldenCliffhangerHook
    episode_end_physical_delta: EpisodeEndPhysicalDelta
    audit_report: StageAuditReport
    # 兼容与扩展字段
    episode_num: int
    title: str
    body_markdown: str
    hook_3s: str
    ending_cliffhanger: str
    outgoing_physical_snapshot: dict[str, Any]
    scene_header: str
    characters_present: list[str]
    core_props: list[str]
    commercial_tag: str
    ast_data: dict[str, Any]


class GoldenCliffhangerHookModel(BaseModel):
    """【规则编号: RULE-II-02 / RULE-VI-05】结尾黄金悬念钩子三位一体结构化模型。"""
    model_config = ConfigDict(extra="allow")
    physical_crisis_action: str = Field(default="", description="物理危机动作（如两人在碎石路上对峙，刀锋抵喉）")
    cliffhanger_dialogue: str = Field(default="", description="绝杀对白（如‘这是小县城，这里没有头条只有过日子！’）")
    acoustic_drop_cue: str = Field(default="[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！", description="声学骤停/重击标记")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            action = d.get("physical_crisis_action") or d.get("hook_action") or d.get("action") or ""
            dialogue = d.get("cliffhanger_dialogue") or d.get("hook_dialogue") or d.get("dialogue") or ""
            acoustic = d.get("acoustic_drop_cue") or d.get("hook_audio_braam") or d.get("audio_cue") or "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
            d["physical_crisis_action"] = str(action)
            d["cliffhanger_dialogue"] = str(dialogue)
            d["acoustic_drop_cue"] = str(acoustic)
            # 同时保留 legacy 别名
            d.setdefault("hook_action", str(action))
            d.setdefault("hook_dialogue", str(dialogue))
            d.setdefault("hook_audio_braam", str(acoustic))
            return d
        return data

    @property
    def hook_action(self) -> str:
        return self.physical_crisis_action

    @property
    def hook_dialogue(self) -> str:
        return self.cliffhanger_dialogue

    @property
    def hook_audio_braam(self) -> str:
        return self.acoustic_drop_cue

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["physical_crisis_action"] = self.physical_crisis_action
        d["cliffhanger_dialogue"] = self.cliffhanger_dialogue
        d["acoustic_drop_cue"] = self.acoustic_drop_cue
        d["hook_action"] = self.hook_action
        d["hook_dialogue"] = self.hook_dialogue
        d["hook_audio_braam"] = self.hook_audio_braam
        return d

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)


class EpisodeEndPhysicalDeltaModel(BaseModel):
    """【规则编号: RULE-II-02 / RULE-VI-05】集尾物理状态快照模型 (封存最后一秒真实物理残局)。"""
    model_config = ConfigDict(extra="allow")
    timeline_progress: str = Field(default="", description="时间线进度（故事时间、倒计时等）")
    character_pose: str = Field(default="", description="角色身体姿态、动作与微表情")
    held_props_and_injuries: str = Field(default="", description="手持道具位置、状态与肉体伤势")
    environment_and_weather: str = Field(default="", description="环境物理与天气光影状态")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            # 提取时间线
            time_val = d.get("timeline_progress") or d.get("timeline_progress_sec") or d.get("timeline") or ""
            if isinstance(time_val, (int, float)):
                time_val = f"单集第 {time_val} 秒"
            # 提取角色姿态
            c_pose = d.get("character_pose") or d.get("posture_and_injuries") or ""
            if not c_pose and isinstance(d.get("character_states"), dict):
                c_pose = "; ".join(f"{k}: {v}" for k, v in d["character_states"].items())
            # 提取道具与伤残
            props_injuries = d.get("held_props_and_injuries") or d.get("carried_props_status") or ""
            if not props_injuries and isinstance(d.get("prop_possession"), dict):
                props_injuries = "; ".join(f"{k}: {v}" for k, v in d["prop_possession"].items())
            # 提取环境与天气
            env_weather = d.get("environment_and_weather") or d.get("weather_and_light") or d.get("environmental_state") or d.get("location") or ""
            
            d["timeline_progress"] = str(time_val)
            d["character_pose"] = str(c_pose)
            d["held_props_and_injuries"] = str(props_injuries)
            d["environment_and_weather"] = str(env_weather)

            # 保留 legacy 别名
            d.setdefault("timeline_progress_sec", 120.0)
            d.setdefault("posture_and_injuries", str(c_pose))
            d.setdefault("carried_props_status", str(props_injuries))
            d.setdefault("weather_and_light", str(env_weather))
            d.setdefault("freeze_frame_desc", d.get("freeze_frame_desc") or str(c_pose))
            return d
        return data

    @property
    def posture_and_injuries(self) -> str:
        return self.character_pose

    @property
    def carried_props_status(self) -> str:
        return self.held_props_and_injuries

    @property
    def weather_and_light(self) -> str:
        return self.environment_and_weather

    @property
    def timeline_progress_sec(self) -> float:
        val = getattr(self, "__pydantic_extra__", {}).get("timeline_progress_sec") if self.__pydantic_extra__ else None
        return float(val) if val is not None else 120.0

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["timeline_progress"] = self.timeline_progress
        d["character_pose"] = self.character_pose
        d["held_props_and_injuries"] = self.held_props_and_injuries
        d["environment_and_weather"] = self.environment_and_weather
        d["timeline_progress_sec"] = self.timeline_progress_sec
        d["posture_and_injuries"] = self.posture_and_injuries
        d["carried_props_status"] = self.carried_props_status
        d["weather_and_light"] = self.weather_and_light
        return d

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)


class PreviousEpisodePickupModel(BaseModel):
    """【规则编号: RULE-II-02 / RULE-VI-05】0 秒接棒物理快照模型 (第 2 集及之后强制包含)。"""
    model_config = ConfigDict(extra="allow")
    inherited_from_episode: int = Field(default=0, description="继承自上一集的集数编号")
    pickup_state_description: str = Field(default="", description="接棒物理状态描写（身体姿态/手持道具/环境伤势）")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            ep_from = d.get("inherited_from_episode") or d.get("episode_index") or d.get("inherited_from") or 0
            desc = d.get("pickup_state_description") or d.get("freeze_frame_desc") or d.get("description") or d.get("pickup_desc") or ""
            d["inherited_from_episode"] = int(ep_from) if str(ep_from).isdigit() else 0
            d["pickup_state_description"] = str(desc)
            # legacy alias
            d.setdefault("freeze_frame_desc", str(desc))
            return d
        return data

    @property
    def freeze_frame_desc(self) -> str:
        return self.pickup_state_description

    @property
    def episode_index(self) -> int:
        return self.inherited_from_episode

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["inherited_from_episode"] = self.inherited_from_episode
        d["pickup_state_description"] = self.pickup_state_description
        d["freeze_frame_desc"] = self.freeze_frame_desc
        d["episode_index"] = self.episode_index
        return d

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)


class LiteraryScreenplayEpisodeModel(BaseModel):
    """【规则编号: RULE-VI-05】阶段 5 标准单集文学剧本模型 (episodes_screenplay/ep_XX.json)。"""
    model_config = ConfigDict(extra="allow")
    episode_id: int = Field(default=1, description="集数编号 (1..NN)")
    episode_title: str = Field(default="", description="单集文学剧本规范标题")
    planned_duration_sec: float = Field(default=120.0, description="单集规划秒数 (如 120.0)")
    dramatic_arc_unit: str = Field(default="", description="所属戏剧微弧单元 (如：单元 A (第 01 - 03 集) · 阶段 A 防御与伪装期)")
    core_dramatic_task: str = Field(default="", description="单集核心戏剧任务/冲突卡点")
    previous_episode_0s_pickup: PreviousEpisodePickupModel | None = Field(default=None, description="上集 0 秒接棒物理快照 (第 2 集起必填)")
    screenplay_text: str = Field(default="", description="影视级标准文学剧本正文 (含时空场景标头、动作行动词、发声阻力括注、对白与三大声学标记)")
    golden_cliffhanger_hook: GoldenCliffhangerHookModel = Field(default_factory=GoldenCliffhangerHookModel, description="结尾三位一体黄金悬念钩子")
    episode_end_physical_delta: EpisodeEndPhysicalDeltaModel = Field(default_factory=EpisodeEndPhysicalDeltaModel, description="集尾最后一秒四维物理快照")
    audit_report: dict[str, Any] = Field(default_factory=dict, description="单阶段红蓝对抗自审汇报")

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            ep_id = d.get("episode_id") or d.get("episode_num") or d.get("episode_number") or 1
            d["episode_id"] = int(ep_id) if str(ep_id).isdigit() else 1
            title = d.get("episode_title") or d.get("title") or f"第{d['episode_id']:02d}集"
            d["episode_title"] = str(title)
            dur = d.get("planned_duration_sec") or d.get("duration_seconds") or d.get("duration") or 120.0
            d["planned_duration_sec"] = float(dur)
            d["dramatic_arc_unit"] = str(d.get("dramatic_arc_unit") or f"单元 {(d['episode_id'] - 1) // 3 + 1}")
            d["core_dramatic_task"] = str(d.get("core_dramatic_task") or d.get("core_conflict_task") or "")
            
            # pickup
            pickup = d.get("previous_episode_0s_pickup") or d.get("previous_episode_physical_pickup") or d.get("incoming_physical_snapshot")
            if pickup:
                if isinstance(pickup, PreviousEpisodePickupModel):
                    d["previous_episode_0s_pickup"] = pickup
                elif isinstance(pickup, dict):
                    d["previous_episode_0s_pickup"] = PreviousEpisodePickupModel.model_validate(pickup)
            elif d["episode_id"] == 1:
                d["previous_episode_0s_pickup"] = None

            # screenplay_text
            text = d.get("screenplay_text") or d.get("body_markdown") or d.get("screenplay_content") or ""
            d["screenplay_text"] = str(text)

            # golden_cliffhanger_hook
            hook = d.get("golden_cliffhanger_hook") or {}
            if isinstance(hook, GoldenCliffhangerHookModel):
                d["golden_cliffhanger_hook"] = hook
            elif isinstance(hook, dict):
                d["golden_cliffhanger_hook"] = GoldenCliffhangerHookModel.model_validate(hook)
            else:
                d["golden_cliffhanger_hook"] = GoldenCliffhangerHookModel(physical_crisis_action=str(hook))

            # episode_end_physical_delta
            delta = d.get("episode_end_physical_delta") or d.get("outgoing_physical_snapshot") or {}
            if isinstance(delta, EpisodeEndPhysicalDeltaModel):
                d["episode_end_physical_delta"] = delta
            elif isinstance(delta, dict):
                d["episode_end_physical_delta"] = EpisodeEndPhysicalDeltaModel.model_validate(delta)
            else:
                d["episode_end_physical_delta"] = EpisodeEndPhysicalDeltaModel(character_pose=str(delta))

            # audit_report
            ar = d.get("audit_report") or {}
            if hasattr(ar, "model_dump"):
                ar = ar.model_dump()
            d["audit_report"] = ar if isinstance(ar, dict) else {}

            # 保留 legacy 别名
            d.setdefault("episode_num", d["episode_id"])
            d.setdefault("title", title)
            d.setdefault("body_markdown", text)
            d.setdefault("outgoing_physical_snapshot", d["episode_end_physical_delta"].model_dump() if hasattr(d["episode_end_physical_delta"], "model_dump") else d["episode_end_physical_delta"])
            return d
        return data

    @property
    def episode_num(self) -> int:
        return self.episode_id

    @property
    def title(self) -> str:
        return self.episode_title

    @property
    def body_markdown(self) -> str:
        return self.screenplay_text

    @property
    def outgoing_physical_snapshot(self) -> EpisodeEndPhysicalDeltaModel:
        return self.episode_end_physical_delta

    def get(self, key: str, default: Any = None) -> Any:
        val = getattr(self, key, None)
        if val is not None:
            return val
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            return self.__pydantic_extra__.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            if self.__pydantic_extra__ is None:
                self.__pydantic_extra__ = {}
            self.__pydantic_extra__[key] = value

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (self.__pydantic_extra__ is not None and key in self.__pydantic_extra__)

    def keys(self) -> list[str]:
        base_keys = list(self.model_fields.keys()) + ["episode_num", "title", "body_markdown", "outgoing_physical_snapshot"]
        if self.__pydantic_extra__:
            base_keys.extend(self.__pydantic_extra__.keys())
        return list(dict.fromkeys(base_keys))

    def items(self) -> list[tuple[str, Any]]:
        return [(k, self.get(k)) for k in self.keys()]

    def values(self) -> list[Any]:
        return [self.get(k) for k in self.keys()]

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["episode_num"] = self.episode_id
        d["title"] = self.episode_title
        d["body_markdown"] = self.screenplay_text
        d["outgoing_physical_snapshot"] = self.episode_end_physical_delta.model_dump()
        return d


__all__ = [
    "EpisodeScriptV2",
    "SeasonOutlineCard",
    "InterEpisodePhysicalContinuity",
    "PreviousEpisodePickup",
    "GoldenCliffhangerHook",
    "EpisodeEndPhysicalDelta",
    "LiteraryScreenplayEpisode",
    "GoldenCliffhangerHookModel",
    "EpisodeEndPhysicalDeltaModel",
    "PreviousEpisodePickupModel",
    "LiteraryScreenplayEpisodeModel",
]
