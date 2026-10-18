"""阶段 6 步骤 1：上游关键依赖提取与单集物理上下文归一化 (Step 1 Context Normalizer)。

本模块实现 `ContextNormalizerStep`，负责统一提取与规整阶段 6 所需的上游关键依赖：
1. 提取当前集剧本正文（兼容 EpisodeScopedSubState、completed_screenplays 及多源降级）；
2. 提取并建立已知角色（Stage 2）、场景与道具（Stage 3）的白名单及 Token 集合；
3. 执行随身锚点道具桥接（将角色档案中的 carried_anchor_item / anchor_props 注入已知物证列表）；
4. 提取全局视听圣经（画幅比例、视听基调风格、下游视频引擎）；
5. 执行跨集 0 秒物理接力快照提取（严格执行首集硬隔离法则与非首集来源校验）。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.tools.screenplay_feature_scanner import _extract_anchor_props_from_characters
from app.workflows.nodes.stage6.helpers import (
    _extract_screenplay_text,
    _get_val,
)
from app.workflows.nodes.stage6.steps.base import BaseStage6Step
from app.workflows.nodes.stage6.steps.context import Stage6StepContext
from app.workflows.nodes.stage6.steps.flags import Stage6StepFlag

logger = logging.getLogger("lmd.stage6.step1_normalize")


class ContextNormalizerStep(BaseStage6Step):
    """【步骤 1 处理器】上游依赖提取与单集物理上下文归一化。

    详细说明：
        作为阶段 6 流水线的首道工序，负责屏蔽上游不同 State 结构（全局图状态、单集子切片状态、
        字典格式测试桩）的异构性，输出结构标准化的上下文数据供后续各算子与模型安全消费。
    """

    def __init__(self) -> None:
        """初始化步骤 1 归一化处理器，绑定 NORMALIZED 状态旗帜。"""
        super().__init__(
            name="Step1_ContextNormalizer",
            flag=Stage6StepFlag.NORMALIZED,
        )

    def execute(self, ctx: Stage6StepContext) -> None:
        """【执行契约】执行上游依赖解析与单集物理快照归一化。

        业务逻辑：
            1. 计算当前集集数（ep_num），多级回退兼容不同字段；
            2. 提取当前集剧本内容对象并抽取纯剧本文本；
            3. 解析上游角色引擎（Stage 2）与场景道具引擎（Stage 3）数据，
               兼容单集轻量切片桩（relevant_character_stubs/relevant_scene_stubs）；
            4. 将角色档案内的随身物证锚点道具注入已知物证列表；
            5. 计算并构建三类实体的唯一 Token 白名单集合；
            6. 解析阶段 1 视听圣经参数（画幅、基调风格、生成引擎）；
            7. 回溯上一集物理快照（首集硬隔离，非首集防脏残留校验）。

        Args:
            ctx (Stage6StepContext): 阶段 6 统一全生命周期上下文容器。

        Raises:
            ValueError: 当无法从上下文中获取任何有效的状态对象时抛出。
        """
        state = ctx.state
        if state is None:
            raise ValueError("【阶段 6 步骤 1 异常】ctx.state 不能为空，上游状态缺失！")

        logger.debug("【阶段 6 步骤 1】开始提取上游关键依赖与归一化单集上下文...")

        # ---------------------------------------------------------------------
        # 1. 提取当前集集数
        # ---------------------------------------------------------------------
        ep_num = (
            _get_val(state, "episode_number")
            or _get_val(state, "current_episode")
            or _get_val(state, "current_visual_episode", 1)
            or 1
        )
        ctx.episode_number = int(ep_num)

        # ---------------------------------------------------------------------
        # 2. 提取当前集剧本对象与纯剧本文本
        # ---------------------------------------------------------------------
        completed = _get_val(state, "completed_screenplays", {}) or {}
        script = completed.get(ep_num) or completed.get(str(ep_num)) or {}
        if not script and _get_val(state, "episodes_scripts"):
            scripts_list = _get_val(state, "episodes_scripts")
            if isinstance(scripts_list, list) and len(scripts_list) >= ep_num:
                script = scripts_list[ep_num - 1]
        if not script and _get_val(state, "episode_script"):
            script = _get_val(state, "episode_script")
        if not script and _get_val(state, "screenplay"):
            script = _get_val(state, "screenplay")
        if not script and _get_val(state, "screenplay_text"):
            script = {
                "body_markdown": _get_val(state, "screenplay_text"),
                "text": _get_val(state, "screenplay_text"),
            }
        if hasattr(script, "model_dump"):
            script = script.model_dump()
        elif not isinstance(script, dict):
            script = {}
        ctx.script = script
        ctx.screenplay_text = _extract_screenplay_text(script)

        # ---------------------------------------------------------------------
        # 3. 提取上游角色引擎 (Stage 2) 与场景道具引擎 (Stage 3) 数据
        # ---------------------------------------------------------------------
        chars_engine = _get_val(state, "characters_engine", None)
        if not chars_engine:
            chars_engine = _get_val(state, "character_engine", None)
        if not chars_engine and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
            chars_engine = state.__pydantic_extra__.get("character_engine") or state.__pydantic_extra__.get("characters_engine")
        if not chars_engine and hasattr(state, "characters") and getattr(state, "characters"):
            chars_engine = getattr(state, "characters")
        if not chars_engine:
            chars_engine = {}
        ctx.characters_engine = chars_engine

        envs_props = _get_val(state, "environments_and_props", None)
        if not envs_props:
            envs_props = _get_val(state, "environments_props", None)
        if not envs_props and hasattr(state, "__pydantic_extra__") and state.__pydantic_extra__:
            envs_props = state.__pydantic_extra__.get("environments_and_props") or state.__pydantic_extra__.get("environments_props")
        if not envs_props:
            envs_props = {}
        ctx.environments_and_props = envs_props

        if isinstance(chars_engine, list):
            char_list = list(chars_engine)
        elif isinstance(chars_engine, dict):
            char_list = list(chars_engine.get("characters", []))
        else:
            char_list = []

        scene_list = list(envs_props.get("environments") or envs_props.get("scenes") or [])
        prop_list = list(envs_props.get("props") or [])

        # 兼容单集独立切片 EpisodeScopedSubState 中的轻量桩
        if not char_list and _get_val(state, "relevant_character_stubs"):
            char_list = [
                {
                    "character_id": f"CHAR_{c.character_id}" if not str(c.character_id).startswith("CHAR_") else str(c.character_id),
                    "name": c.name,
                    "role_type": c.archetype,
                    "appearance": c.visual_token,
                    "voice_style": c.core_costume_prompt,
                }
                if hasattr(c, "character_id") else c
                for c in _get_val(state, "relevant_character_stubs")
            ]
        if not scene_list and _get_val(state, "relevant_scene_stubs"):
            scene_list = [
                {
                    "env_id": f"ENV_{s.scene_id}" if not str(s.scene_id).startswith("ENV_") else str(s.scene_id),
                    "location_name": s.name,
                    "visual_prompt": s.weathering_summary,
                    "atmosphere": s.color_tone,
                }
                if hasattr(s, "scene_id") else s
                for s in _get_val(state, "relevant_scene_stubs")
            ]
        if not prop_list and _get_val(state, "relevant_prop_stubs"):
            prop_list = [
                {
                    "prop_id": f"PROP_{p.prop_id}" if not str(p.prop_id).startswith("PROP_") else str(p.prop_id),
                    "name": p.name,
                    "type": p.level,
                    "visual_prompt": p.visual_token,
                }
                if hasattr(p, "prop_id") else p
                for p in _get_val(state, "relevant_prop_stubs")
            ]

        # ---------------------------------------------------------------------
        # 4. 【随身物证锚点桥接】将角色档案中的 carried_anchor_item / anchor_props 注入物证列表
        # ---------------------------------------------------------------------
        existing_p_names = {
            str(p.get("name") or p.get("prop_name") or "").strip()
            for p in prop_list
            if isinstance(p, dict) and (p.get("name") or p.get("prop_name"))
        }
        anchor_from_chars = _extract_anchor_props_from_characters(char_list)
        if anchor_from_chars:
            for cap in anchor_from_chars:
                if cap["name"] not in existing_p_names:
                    existing_p_names.add(cap["name"])
                    prop_list.append(cap)
                    logger.debug(
                        "【阶段 6 步骤 1 锚点注入】自动将角色 [%s] 的随身锚点道具 '%s' (%s) 注入本集已知物证列表",
                        cap.get("owner_character", ""),
                        cap["name"],
                        cap["prop_id"],
                    )

        ctx.char_list = char_list
        ctx.scene_list = scene_list
        ctx.prop_list = prop_list

        # ---------------------------------------------------------------------
        # 5. 提取已锁定的 Token 白名单集合
        # ---------------------------------------------------------------------
        ctx.char_tokens = set(
            _get_val(state, "character_tokens")
            or (chars_engine.get("character_tokens") if isinstance(chars_engine, dict) else [])
            or [
                re.sub(r"[^A-Z0-9]+", "", c.get("character_id", "").replace("CHAR_", ""))
                for c in char_list
                if isinstance(c, dict) and c.get("character_id")
            ]
        )
        ctx.scene_tokens = set(
            _get_val(state, "scene_tokens")
            or envs_props.get("scene_tokens")
            or [
                re.sub(r"[^A-Z0-9]+", "", (e.get("env_id") or e.get("environment_id", "")).replace("ENV_", ""))
                for e in scene_list
                if isinstance(e, dict) and (e.get("env_id") or e.get("environment_id"))
            ]
        )
        ctx.prop_tokens = set(
            _get_val(state, "prop_tokens")
            or envs_props.get("prop_tokens")
            or [
                re.sub(r"[^A-Z0-9]+", "", p.get("prop_id", "").replace("PROP_", ""))
                for p in prop_list
                if isinstance(p, dict) and p.get("prop_id")
            ]
        )

        # ---------------------------------------------------------------------
        # 6. 解析视听资产真理源注册表与现有引单
        # ---------------------------------------------------------------------
        reg_raw = _get_val(state, "visual_audio_assets_registry", {}) or {}
        if hasattr(reg_raw, "to_dict"):
            ctx.registry = reg_raw.to_dict()
        elif hasattr(reg_raw, "model_dump"):
            ctx.registry = reg_raw.model_dump()
        elif isinstance(reg_raw, dict):
            ctx.registry = dict(reg_raw)
        else:
            ctx.registry = {}

        ctx.manifests = dict(
            _get_val(state, "episode_resource_manifests", None)
            or _get_val(state, "episode_manifests", {})
            or {}
        )

        # ---------------------------------------------------------------------
        # 7. 提取单集悬念爆款标题 (多层级回退)
        # ---------------------------------------------------------------------
        episode_title = script.get("episode_title") or script.get("title") or ""
        if not episode_title:
            season_outlines = _get_val(state, "season_outlines") or _get_val(state, "season_outline") or {}
            if isinstance(season_outlines, dict):
                outline_ep = season_outlines.get(ep_num) or season_outlines.get(str(ep_num)) or {}
                if isinstance(outline_ep, dict):
                    episode_title = outline_ep.get("title") or outline_ep.get("killer_title") or outline_ep.get("episode_title") or ""
            elif isinstance(season_outlines, list):
                for item in season_outlines:
                    if isinstance(item, dict) and (item.get("episode_num") == ep_num or item.get("episode_id") == ep_num):
                        episode_title = item.get("title") or item.get("killer_title") or item.get("episode_title") or ""
                        break
        if not episode_title:
            episode_title = f"第{ep_num}集"
        ctx.episode_title = episode_title

        # ---------------------------------------------------------------------
        # 8. 提取阶段 1 视听圣经核心参数 (画幅、视觉风格、目标视频生成引擎)
        # ---------------------------------------------------------------------
        bible = _get_val(state, "bible", {}) or {}
        if hasattr(bible, "model_dump"):
            bible = bible.model_dump()
        elif hasattr(bible, "to_dict"):
            bible = bible.to_dict()
        elif not isinstance(bible, dict):
            bible = {}

        ctx.aspect_ratio = (
            _get_val(state, "aspect_ratio")
            or bible.get("aspect_ratio")
            or "9:16"
        )
        ctx.visual_style = (
            _get_val(state, "visual_style")
            or bible.get("visual_style")
            or bible.get("tone_style")
            or "电影质感，冷调颗粒，8k超高清写实，戏剧性侧逆光"
        )
        ctx.target_video_engine = (
            _get_val(state, "target_video_engine")
            or bible.get("target_video_engine")
            or "kling_1.6_high_fidelity"
        )

        # ---------------------------------------------------------------------
        # 8.1 提取题材类型并自适应挂载题材预设包 (Genre Pack)
        # ---------------------------------------------------------------------
        from app.workflows.nodes.stage6.genre_packs import get_genre_pack

        drama_genre = (
            _get_val(state, "drama_genre")
            or _get_val(state, "genre")
            or bible.get("genre")
            or bible.get("drama_genre")
            or ""
        )
        ctx.drama_genre = str(drama_genre or "").strip()
        ctx.genre_pack = get_genre_pack(
            drama_genre=ctx.drama_genre,
            visual_style=ctx.visual_style,
            screenplay_text=ctx.screenplay_text,
        )
        logger.info(
            "【阶段 6 步骤 1 题材感知】当前剧本题材: '%s', 自动绑定题材预设包: [%s] (%s)",
            ctx.drama_genre or "未显式指定",
            ctx.genre_pack.name,
            ctx.genre_pack.label,
        )

        # ---------------------------------------------------------------------
        # 9. 提取上一集 0 秒物理接力快照 (用于跨集战损、创伤及核心物证状态追踪)
        # ---------------------------------------------------------------------
        previous_pickup = None
        if ep_num <= 1:
            # 【首集硬隔离法则】第 1 集为全剧开篇，不存在上一集的物理流出，强制置空以阻断跨轮次全局 state 脏残留
            previous_pickup = None
            logger.info("【阶段 6 步骤 1 物理接力】当前为第 %s 集（开篇集），强制上一集物理快照为 None", ep_num)
        else:
            # 【非首集精准回溯】优先取自第 ep_num - 1 集的定稿剧本交付物（单一事实真理源）
            prev_script = completed.get(ep_num - 1) or completed.get(str(ep_num - 1)) or {}
            if isinstance(prev_script, dict):
                previous_pickup = (
                    prev_script.get("inter_episode_physical_snapshot")
                    or prev_script.get("previous_episode_0s_pickup")
                    or prev_script.get("pickup_0s")
                )
            # 仅当上一集定稿剧本未显式登记快照时，才降级读取全局流水线状态
            if not previous_pickup:
                fallback = _get_val(state, "inter_episode_physical_snapshot", None) or _get_val(state, "incoming_physical_continuity", None)
                if isinstance(fallback, dict):
                    # 校验来源集数，防止误读更晚剧集残留的脏快照
                    source_ep = fallback.get("source_episode") or fallback.get("episode_num") or fallback.get("inherited_from_episode")
                    if source_ep is None or source_ep == ep_num - 1:
                        previous_pickup = fallback

        ctx.previous_pickup = previous_pickup

        logger.debug(
            "【阶段 6 步骤 1 完成】第 %s 集依赖就绪: 剧本长度=%d 字符, 已知角色=%d, 已知场景=%d, 已知道具=%d, 物理接力存在=%s",
            ep_num,
            len(ctx.screenplay_text),
            len(ctx.char_list),
            len(ctx.scene_list),
            len(ctx.prop_list),
            bool(ctx.previous_pickup),
        )
