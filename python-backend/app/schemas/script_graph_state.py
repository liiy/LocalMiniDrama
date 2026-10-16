# -*- coding: utf-8 -*-
"""LangGraph 短剧工业化创作状态数据契约门面 (Drama Script State Schema Facade)。

【架构解耦说明】
原单体大文件已按关注点分离原则拆解至 `app.schemas.states` 领域子包：
- core.py: 企划、世界观、人物画像、大纲与瘦状态机
- audit.py: 红蓝对抗与质检审计契约
- audio.py: 声音资产、母带规范与音频圣经
- asset.py: 资产真理层、多模态资产注册清单
- storyboard.py: 分镜镜头、口型动态与媒体配置
- screenplay.py: 文学剧本、集间物理状态连续性与钩子
- master.py: 全局工业主图状态（GlobalDramaMasterState等）与单集子状态

本门面保留完整向后兼容性，所有旧版 `from app.schemas.script_graph_state import ...` 导入完全不受影响。
"""
from __future__ import annotations

import logging

from app.schemas.states import *  # noqa: F401, F403
from app.schemas.states import __all__ as _states_all

logger = logging.getLogger("app.schemas.script_graph_state")
logger.debug("已加载状态契约领域门面模块 app.schemas.script_graph_state")

__all__ = _states_all
