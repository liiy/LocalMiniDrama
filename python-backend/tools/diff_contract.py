"""Node vs Python 契约对拍：同一批请求分别打到两端，归一化动态字段后比对 JSON。

目的：把「契约等价」从人工断言升级为自动 diff，捕捉序列化差异
（null vs 缺省、数字 vs 字符串、字段缺失、错误消息不一致等）。

Node 端：tools/node_probe.js（内存 SQLite，只读加载 backend-node，不触碰真实数据文件）
Python 端：TestClient（远程测试库 drama_genertor_test）

归一化规则（忽略必然不同的动态值）：
- 顶层 timestamp
- 所有 created_at / updated_at / id（自增主键两端不同步）
- deleted_at
- completed_at（任务完成时刻的墙钟值，两端必然不同；其"是否被设置"由 pytest 断言覆盖）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("LMD_CONFIG_PATH", str(ROOT / "configs" / "config.yaml"))
os.environ["LMD_DATABASE_URL"] = (
    "mysql+pymysql://admin:1qaz2wsX%21@117.72.149.170:3306/drama_genertor_test?charset=utf8mb4"
)

NODE_PORT = 5699
BASE = f"http://127.0.0.1:{NODE_PORT}"

TTS_STUB_PORT = 5701
# 假 MP3 字节：TTS stub 始终返回它，两端写入的 local_path 结构一致即可对拍
_FAKE_MP3 = b"ID3\x00\x00\x00\x00\x00\x00FAKE_MP3_AUDIO_BYTES"

# 用例：(method, path, body)
CASES: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/v1/settings/prompts", None),
    ("PUT", "/api/v1/settings/prompts/character_extraction", {"content": "  自定义内容  "}),
    ("GET", "/api/v1/settings/prompts", None),
    ("PUT", "/api/v1/settings/prompts/nope", {"content": "x"}),
    ("DELETE", "/api/v1/settings/prompts/nope", None),
    ("PUT", "/api/v1/settings/prompts/prop_extraction", {"content": "   "}),
    ("DELETE", "/api/v1/settings/prompts/character_extraction", None),
    ("GET", "/api/v1/settings/prompts", None),
    ("GET", "/api/v1/scene-model-map", None),
    ("POST", "/api/v1/scene-model-map", {"key": "scene_a", "description": "A"}),
    ("POST", "/api/v1/scene-model-map", {"key": "scene_a"}),
    ("POST", "/api/v1/scene-model-map", {"description": "no key"}),
    ("GET", "/api/v1/scene-model-map/scene_a", None),
    ("PUT", "/api/v1/scene-model-map/scene_a", {"service_type": "image", "config_id": 7, "model_override": "m1"}),
    ("GET", "/api/v1/scene-model-map/scene_a", None),
    ("GET", "/api/v1/scene-model-map/ghost", None),
    ("PUT", "/api/v1/scene-model-map/ghost", {}),
    ("DELETE", "/api/v1/scene-model-map/ghost", None),
    ("DELETE", "/api/v1/scene-model-map/scene_a", None),
    ("GET", "/api/v1/scene-model-map", None),
]

# library 对拍：三个库 × 一套 CRUD
for lib, payload in (
    ("/api/v1/character-library", {"name": "林晚", "description": "女主", "category": "主角"}),
    ("/api/v1/scene-library", {"location": "卧室内", "time": "清晨", "prompt": "古风卧室", "category": "室内"}),
    ("/api/v1/prop-library", {"name": "玉佩", "description": "信物", "prompt": "羊脂玉佩", "category": "道具"}),
):
    CASES += [
        ("GET", lib, None),
        ("POST", lib, {**payload, "source_type": "manual"}),
        ("GET", f"{lib}/1", None),
        ("PUT", f"{lib}/1", {"category": "改后"}),
        ("PUT", f"{lib}/1", {"source_id": "  S7  "}),
        ("GET", lib, None),
        ("GET", f"{lib}/999999", None),
        ("PUT", f"{lib}/999999", {"category": "x"}),
        ("DELETE", f"{lib}/999999", None),
        ("DELETE", f"{lib}/1", None),
        ("GET", lib, None),
        ("POST", lib, {}),
        ("GET", f"{lib}?page=1&page_size=2", None),
        ("GET", f"{lib}?page_size=999", None),
        ("GET", f"{lib}?page_size=0", None),
        ("GET", f"{lib}?page=abc", None),
        ("GET", f"{lib}?global=1", None),
        ("GET", f"{lib}?drama_id=3", None),
        ("GET", f"{lib}?source_id=S1", None),
        ("GET", f"{lib}?source_ids=S1,S2", None),
        ("GET", f"{lib}?source_ids=S1&source_ids=S2", None),
        ("GET", f"{lib}?category=兵器", None),
        ("GET", f"{lib}?keyword=玉", None),
    ]

# dramas 对拍：CRUD + 各类保存端点
CASES += [
    ("POST", "/api/v1/dramas", {"description": "x"}),
    ("POST", "/api/v1/dramas", {"title": "   "}),
    ("POST", "/api/v1/dramas", {"title": "测试剧本"}),
    ("GET", "/api/v1/dramas", None),
    ("GET", "/api/v1/dramas/stats", None),
    ("GET", "/api/v1/dramas/1", None),
    ("GET", "/api/v1/dramas/999999", None),
    ("PUT", "/api/v1/dramas/1", {"title": "改名", "status": "completed"}),
    ("PUT", "/api/v1/dramas/1/outline", {"title": "大纲", "summary": "梗概", "genre": "古装", "tags": ["a"], "style": "ink wash"}),
    ("GET", "/api/v1/dramas/1", None),
    ("PUT", "/api/v1/dramas/1/episodes", {"episodes": "x"}),
    ("PUT", "/api/v1/dramas/1/episodes", {"episodes": [{"episode_number": 1, "title": "第一集", "script_content": "内容", "duration": 60}, {"episode_number": 2, "title": "第二集"}]}),
    ("GET", "/api/v1/dramas/1", None),
    ("PUT", "/api/v1/dramas/1/characters", {"characters": "x"}),
    ("PUT", "/api/v1/dramas/1/characters", {"characters": [{"name": "林晚", "role": "main", "appearance": "青衫"}, {"name": "苏明", "role": "supporting"}]}),
    ("GET", "/api/v1/dramas/1/characters", None),
    ("GET", "/api/v1/dramas/1/characters?episode_id=1", None),
    ("GET", "/api/v1/dramas/1/characters?episode_id=999999", None),
    ("PUT", "/api/v1/dramas/1/progress", {}),
    ("PUT", "/api/v1/dramas/1/progress", {"current_step": "story", "step_data": {"k": 1}}),
    ("GET", "/api/v1/dramas/1", None),
    ("PUT", "/api/v1/dramas/1/canvas-layout", {}),
    ("PUT", "/api/v1/dramas/1/canvas-layout", {"canvas_layout": [1, 2]}),
    ("PUT", "/api/v1/dramas/1/canvas-layout", {"canvas_layout": "x", "workflow_groups": []}),
    ("PUT", "/api/v1/dramas/1/canvas-layout", {"workflow_groups": {"a": 1}}),
    ("PUT", "/api/v1/dramas/1/canvas-layout", {"canvas_layout": {"nodes": {"n1": {}}}, "workflow_groups": [{"id": "g1"}]}),
    ("GET", "/api/v1/dramas/1/props", None),
    ("GET", "/api/v1/dramas/1", None),
    ("GET", "/api/v1/dramas?genre=古装", None),
    ("GET", "/api/v1/dramas?status=completed", None),
    ("GET", "/api/v1/dramas?keyword=大纲", None),
    ("GET", "/api/v1/dramas?page=2&page_size=1", None),
    ("DELETE", "/api/v1/dramas/1", None),
    ("DELETE", "/api/v1/dramas/1", None),
    ("GET", "/api/v1/dramas", None),
    ("GET", "/api/v1/dramas/stats", None),
]

# 实体 CRUD 对拍（characters / scenes / props / storyboards）
CASES += [
    ("POST", "/api/v1/dramas", {"title": "实体对拍剧"}),
    ("PUT", "/api/v1/dramas/1/characters", {"characters": [{"name": "对拍角色", "appearance": "青衫"}]}),
    ("GET", "/api/v1/dramas/1/characters", None),
    ("GET", "/api/v1/characters/1", None),
    ("GET", "/api/v1/characters/999999", None),
    ("PUT", "/api/v1/characters/1", {"name": "改名", "appearance": "红衣"}),
    ("GET", "/api/v1/characters/1", None),
    ("PUT", "/api/v1/characters/1", {}),
    ("PUT", "/api/v1/characters/999999", {"name": "x"}),
    ("DELETE", "/api/v1/characters/999999", None),
    ("POST", "/api/v1/scenes", {"location": "x"}),
    ("POST", "/api/v1/scenes", {"drama_id": 1, "location": "卧室内", "time": "清晨", "prompt": "古风卧室"}),
    ("GET", "/api/v1/scenes/1", None),
    ("PUT", "/api/v1/scenes/1", {"location": "书房", "ref_image": None}),
    ("GET", "/api/v1/scenes/1", None),
    ("PUT", "/api/v1/scenes/1/prompt", {"prompt": "新提示词"}),
    ("PUT", "/api/v1/scenes/1/prompt", {}),
    ("GET", "/api/v1/scenes/1", None),
    ("GET", "/api/v1/scenes/999999", None),
    ("DELETE", "/api/v1/scenes/1", None),
    ("DELETE", "/api/v1/scenes/1", None),
    ("POST", "/api/v1/props", {"name": "无drama"}),
    ("POST", "/api/v1/props", {"drama_id": 1, "name": "玉佩", "type": "信物", "prompt": "羊脂玉佩"}),
    ("GET", "/api/v1/props/1", None),
    ("PUT", "/api/v1/props/1", {"name": "长剑", "description": "兵器"}),
    ("GET", "/api/v1/props/1", None),
    ("GET", "/api/v1/props/abc", None),
    ("PUT", "/api/v1/props/abc", {"name": "x"}),
    ("DELETE", "/api/v1/props/abc", None),
    ("GET", "/api/v1/props/999999", None),
    ("DELETE", "/api/v1/props/1", None),
    # props add-to-library / add-to-material-library（纯 DB 关联，真实同步）
    ("POST", "/api/v1/__seed/drama", {"id": 8800, "title": "对拍剧-道具库", "created_at": "2026-01-02T00:00:00.000Z"}),
    ("POST", "/api/v1/__seed/prop", {"id": 8701, "drama_id": 8800, "name": "玉佩", "type": "信物",
                                     "image_url": "http://cdn.example/yupei.png", "local_path": "prop/yupei.png"}),
    ("POST", "/api/v1/__seed/prop", {"id": 8702, "drama_id": 8800, "name": "无图道具", "type": "x"}),
    ("POST", "/api/v1/props/8701/add-to-library", None),
    ("POST", "/api/v1/props/8701/add-to-material-library", None),
    ("POST", "/api/v1/props/8702/add-to-library", None),  # 无图 → 400
    ("POST", "/api/v1/props/999999/add-to-library", None),  # 不存在 → 404
    ("POST", "/api/v1/props/abc/add-to-library", None),  # 非法 id → 400
    ("GET", "/api/v1/prop-library?drama_id=1", None),
    # scenes add-to-library / add-to-material-library（纯 DB 关联，真实同步）
    ("POST", "/api/v1/__seed/scene", {"id": 8601, "drama_id": 8800, "image_url": "http://cdn.example/scene1.png",
                                      "local_path": "scene/s1.png"}),
    ("POST", "/api/v1/__seed/scene", {"id": 8602, "drama_id": 8800}),
    ("POST", "/api/v1/scenes/8601/add-to-library", None),
    ("POST", "/api/v1/scenes/8601/add-to-material-library", None),
    ("POST", "/api/v1/scenes/8602/add-to-library", None),  # 无图 → 400
    ("POST", "/api/v1/scenes/999999/add-to-library", None),  # 不存在 → 404
    ("POST", "/api/v1/scenes/abc/add-to-library", None),  # 非法 id → 404
    ("GET", "/api/v1/scene-library?drama_id=8800", None),
    # characters 关联端点（真实同步，纯 DB / 文件）
    ("POST", "/api/v1/__seed/character", {"id": 8501, "drama_id": 8800, "name": "小雪", "image_url": "http://cdn.example/xiaoxue.png",
                                          "local_path": "character/xiaoxue.png", "appearance": "黑长直发"}),
    ("POST", "/api/v1/__seed/character", {"id": 8502, "drama_id": 8800, "name": "无图角色"}),
    ("POST", "/api/v1/__seed/character-library", {"id": 85001, "drama_id": 8800, "name": "库项小雪",
                                                  "image_url": "http://cdn.example/lib_xiaoxue.png", "local_path": "character/lib_xiaoxue.png",
                                                  "source_type": "character", "source_id": 8501}),
    ("PUT", "/api/v1/characters/8501/image-from-library", {"library_id": 85001}),
    ("PUT", "/api/v1/characters/8501/image-from-library", {"library_id": 999999}),  # 库项不存在 → 404
    ("PUT", "/api/v1/characters/8501/image-from-library", {}),  # 缺 library_id → 400
    ("POST", "/api/v1/characters/8501/add-to-library", {"category": "女主"}),
    ("POST", "/api/v1/characters/8501/add-to-material-library", None),
    ("POST", "/api/v1/characters/8502/add-to-library", {"category": "x"}),  # 无图 → 400
    ("POST", "/api/v1/characters/999999/add-to-library", None),  # 不存在 → 404
    ("PUT", "/api/v1/characters/8501/image", {"image_url": "http://cdn.example/xiaoxue2.png"}),
    ("POST", "/api/v1/characters/8501/extract-anchors", None),
    ("POST", "/api/v1/characters/999999/extract-anchors", None),  # 不存在 → 404
    ("POST", "/api/v1/characters/8502/extract-anchors", None),  # 缺 appearance → 400
    ("POST", "/api/v1/characters/8501/sd2-voice-refresh", None),
    ("GET", "/api/v1/character-library?drama_id=8800", None),
    ("PUT", "/api/v1/dramas/1/episodes", {"episodes": [{"episode_number": 1, "title": "E1"}]}),
    ("POST", "/api/v1/storyboards", {"episode_id": 1, "storyboard_number": 1, "title": "开场", "duration": 5}),
    ("GET", "/api/v1/storyboards/1", None),
    ("PUT", "/api/v1/storyboards/1", {"title": "改后", "duration": 8}),
    ("GET", "/api/v1/storyboards/1", None),
    ("PUT", "/api/v1/storyboards/1", {"characters": [1]}),
    ("PUT", "/api/v1/storyboards/1", {"character_ids": [1, 1]}),
    ("PUT", "/api/v1/storyboards/1", {"characters": "not-json"}),
    ("GET", "/api/v1/storyboards/1", None),
    ("POST", "/api/v1/storyboards/2/insert-before", None),
    ("POST", "/api/v1/storyboards/999999/insert-before", None),
    ("GET", "/api/v1/storyboards/999999", None),
    ("DELETE", "/api/v1/storyboards/1", None),
    ("DELETE", "/api/v1/storyboards/1", None),
    ("GET", "/api/v1/dramas/1", None),
    # batch-infer-params（纯推断，无 AI）：seed 一个含文本但无摄影参数的分镜后批量补全
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "夜色中霓虹灯下的特写镜头", "narration": ""}),
    ("POST", "/api/v1/storyboards/batch-infer-params", {"episode_id": 1, "overwrite": False}),
    ("POST", "/api/v1/storyboards/batch-infer-params", {"episode_id": 999999, "overwrite": False}),
    ("POST", "/api/v1/storyboards/batch-infer-params", {"episode_id": None, "overwrite": False}),
    # frame-prompts（纯同步：GET 列表 / PUT 保存）
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "测试分镜", "narration": ""}),
    ("GET", "/api/v1/storyboards/1/frame-prompts", None),
    ("PUT", "/api/v1/storyboards/1/frame-prompts/first", {"prompt": "开场镜头提示词", "description": "远景", "layout": "grid(2x2)"}),
    ("GET", "/api/v1/storyboards/1/frame-prompts", None),
    ("PUT", "/api/v1/storyboards/1/frame-prompts/key", {"prompt": "关键帧提示词", "description": None, "layout": None}),
    ("GET", "/api/v1/storyboards/1/frame-prompts", None),
    ("PUT", "/api/v1/storyboards/1/frame-prompts/badtype", {"prompt": "x"}),
    ("PUT", "/api/v1/storyboards/1/frame-prompts/first", {"prompt": ""}),
    # frame-prompt（异步任务骨架：返回 task_id + status=pending）
    ("POST", "/api/v1/storyboards/1/frame-prompt", {"frame_type": "first", "panel_count": 3, "model": ""}),
    ("POST", "/api/v1/storyboards/1/frame-prompt", {"frame_type": "badtype", "panel_count": 3, "model": ""}),
    ("POST", "/api/v1/storyboards/999999/frame-prompt", {"frame_type": "first"}),
    # episode storyboards generate（异步任务骨架：返回 task_id；同步校验剧集/剧本）
    ("POST", "/api/v1/__seed/episode", {"id": 9, "drama_id": 1, "title": "生成测试集", "episode_number": 9, "script_content": "主角走进房间，开始讲述往事。", "description": ""}),
    ("POST", "/api/v1/storyboards/episode/9/generate", {"model": "", "style": "", "storyboard_count": 5, "video_duration": 75, "aspect_ratio": "", "include_narration": True, "universal_omni": False}),
    ("POST", "/api/v1/__seed/episode", {"id": 10, "drama_id": 1, "title": "空剧本集", "episode_number": 10, "script_content": "", "description": ""}),
    ("POST", "/api/v1/storyboards/episode/10/generate", {"model": ""}),
    ("POST", "/api/v1/storyboards/episode/999999/generate", {"model": ""}),
]


# ai-configs 对拍：CRUD + 静态路径 + 代理端点的校验分支（不发真实网络请求）
_VALID_CFG = {
    "service_type": "text",
    "name": "测试文本配置",
    "provider": "openai",
    "base_url": "https://api.example.com/v1",
    "api_key": "sk-test-key",
}

CASES += [
    ("GET", "/api/v1/ai-configs", None),
    ("GET", "/api/v1/ai-configs/vendor-lock", None),
    ("PUT", "/api/v1/ai-configs/bulk-update-key", {"api_key": "sk-new"}),
    ("POST", "/api/v1/ai-configs", {"name": "x"}),
    # 缺少 api_key（Node 用 !== null/undefined 判定）
    ("POST", "/api/v1/ai-configs", {**_VALID_CFG, "api_key": None}),
    ("POST", "/api/v1/ai-configs", {**_VALID_CFG}),
    ("POST", "/api/v1/ai-configs", {**_VALID_CFG, "name": "视频", "service_type": "video"}),
    ("POST", "/api/v1/ai-configs", {**_VALID_CFG, "name": "单模型", "model": "gpt-4o"}),
    ("POST", "/api/v1/ai-configs", {**_VALID_CFG, "name": "多模型", "model": ["a", "b"]}),
    ("POST", "/api/v1/ai-configs", {**_VALID_CFG, "name": "默认模型", "default_model": "  gpt-4o  "}),
    (
        "POST",
        "/api/v1/ai-configs",
        {**_VALID_CFG, "name": "即梦2", "service_type": "jimeng2_character_auth", "api_key": "Bearer abc123"},
    ),
    ("GET", "/api/v1/ai-configs", None),
    ("GET", "/api/v1/ai-configs?service_type=text", None),
    ("GET", "/api/v1/ai-configs/1", None),
    ("GET", "/api/v1/ai-configs/abc", None),
    ("GET", "/api/v1/ai-configs/999999", None),
    ("PUT", "/api/v1/ai-configs/1", {"name": "改名", "priority": 5}),
    ("PUT", "/api/v1/ai-configs/1", {}),
    ("PUT", "/api/v1/ai-configs/1", {"model": ["m1", "m2"]}),
    ("PUT", "/api/v1/ai-configs/abc", {"name": "x"}),
    ("PUT", "/api/v1/ai-configs/999999", {"name": "x"}),
    ("DELETE", "/api/v1/ai-configs/1", None),
    ("DELETE", "/api/v1/ai-configs/1", None),
    ("DELETE", "/api/v1/ai-configs/abc", None),
    ("GET", "/api/v1/ai-configs", None),
    # 代理端点：仅校验分支
    ("POST", "/api/v1/ai-configs/test", {"base_url": "https://x.com"}),
    ("POST", "/api/v1/ai-configs/jimeng2-list-assets", {}),
    ("POST", "/api/v1/ai-configs/model-ark-asset", {"base_url": "https://ark.cn-beijing.volces.com"}),
    ("POST", "/api/v1/ai-configs/model-ark-asset", {"base_url": "https://ark.cn-beijing.volces.com", "action": "Nope"}),
    ("POST", "/api/v1/ai-configs/model-ark-asset", {"action": "ListAssets"}),
    ("POST", "/api/v1/ai-configs/model-ark-asset", {"base_url": "ftp://x.com", "action": "ListAssets"}),
    (
        "POST",
        "/api/v1/ai-configs/model-ark-asset",
        {"base_url": "https://ark.cn-beijing.volces.com", "action": "ListAssets", "auth_mode": "volc_sign"},
    ),
]

# tasks 对拍：静态 404/400 分支 + 用固定 id/created_at 播种后的取消流程
# 注：/api/v1/__seed/* 为 node_probe.js 的对拍专用端点，Python 侧在 call_py 内拦截等价实现
_SEED = "/api/v1/__seed/task"

CASES += [
    ("GET", "/api/v1/tasks/nope", None),
    ("POST", "/api/v1/tasks/nope/cancel", {}),
    ("GET", "/api/v1/tasks", None),
    ("GET", "/api/v1/tasks?resource_id=", None),
    ("GET", "/api/v1/tasks?resource_id=none", None),
    # pending 任务 → 取消后 failed + error=用户已取消
    ("POST", _SEED, {"id": "T1", "type": "gen", "status": "pending", "resource_id": "drama:1",
                     "created_at": "2026-01-01T00:00:01.000Z"}),
    ("POST", _SEED, {"id": "T2", "type": "gen", "status": "pending", "resource_id": "drama:1",
                     "created_at": "2026-01-01T00:00:02.000Z"}),
    ("GET", "/api/v1/tasks/T1", None),
    ("GET", "/api/v1/tasks?resource_id=drama:1", None),
    ("POST", "/api/v1/tasks/T1/cancel", {}),
    ("GET", "/api/v1/tasks/T1", None),
    # 自定义原因（Node 会 trim）
    ("POST", "/api/v1/tasks/T2/cancel", {"reason": "  不要了  "}),
    ("GET", "/api/v1/tasks/T2", None),
    # 已 completed 的任务：cancel 不报错、不改写
    ("POST", _SEED, {"id": "T3", "type": "gen", "status": "completed", "progress": 100,
                     "resource_id": "drama:2", "created_at": "2026-01-01T00:00:03.000Z"}),
    ("POST", "/api/v1/tasks/T3/cancel", {}),
    ("GET", "/api/v1/tasks/T3", None),
    # 已 failed 的任务：cancel 保留原始 error
    ("POST", _SEED, {"id": "T4", "type": "gen", "status": "failed", "resource_id": "drama:2",
                     "created_at": "2026-01-01T00:00:04.000Z"}),
    ("POST", "/api/v1/tasks/T4/cancel", {}),
    ("GET", "/api/v1/tasks/T4", None),
    ("GET", "/api/v1/tasks?resource_id=drama:2", None),
]

# assets 对拍：CRUD + 分页边界 + import 导入分支
# 注：不覆盖 description / thumbnail_url / is_favorite —— Node 的 assets 表无这三列，
#     传入会触发 SQL 错误（SQLite / MySQL 报错文案不同），属 Node 侧既有缺陷，非移植差异。
#
# 确定性说明（重要）：列表类用例统一改用 __seed/asset（显式 created_at）构造数据。
# 原因：POST /assets 的 created_at 由服务端 timestamp()（毫秒精度）生成，而 Node 走真实 HTTP
# （较慢）、Python 走 TestClient（较快），两侧及各次运行的毫秒值可能相同；同毫秒行的相对顺序
# 由 DB 任意决定 → 列表/分页顺序不确定 → 潜在 flaky。
# 此处保留 POST 用例以覆盖「创建」语义（其响应体与顺序无关，始终确定），随后删除这些行，
# 再以确定性种子驱动所有与顺序相关的查询。
CASES += [
    ("GET", "/api/v1/assets", None),
    # —— 创建语义覆盖（响应体确定）——
    ("POST", "/api/v1/assets", {}),
    ("POST", "/api/v1/assets", {"name": "视频素材", "drama_id": 3, "type": "video", "duration": 5.5}),
    ("POST", "/api/v1/assets", {"name": "图1", "drama_id": 1, "type": "image"}),
    ("POST", "/api/v1/assets", {"name": "图2", "drama_id": 2, "type": "image"}),
    # 清理上述行，避免其服务端时间戳影响后续列表顺序判定
    ("DELETE", "/api/v1/assets/1", None),
    ("DELETE", "/api/v1/assets/2", None),
    ("DELETE", "/api/v1/assets/3", None),
    ("DELETE", "/api/v1/assets/4", None),
    ("GET", "/api/v1/assets", None),
    # —— 确定性种子（乱序插入：插入序 9801,9802,9803,9804 对应时间 01,03,04,02）——
    #     DESC 正确序为 9803,9802,9804,9801，与插入序不同，可捕获漏写 ORDER BY 的情况。
    ("POST", "/api/v1/__seed/asset", {"id": 9801, "drama_id": 1, "name": "图1", "type": "image",
                                      "created_at": "2026-04-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/asset", {"id": 9802, "drama_id": 2, "name": "图2", "type": "image",
                                      "created_at": "2026-04-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/asset", {"id": 9803, "drama_id": 3, "name": "视频素材", "type": "video",
                                      "duration": 5.5, "created_at": "2026-04-01T00:00:04.000Z"}),
    ("POST", "/api/v1/__seed/asset", {"id": 9804, "drama_id": 1, "name": "图3", "type": "image",
                                      "created_at": "2026-04-01T00:00:02.000Z"}),
    # —— 列表 / 过滤 / 分页（全部确定）——
    ("GET", "/api/v1/assets", None),
    ("GET", "/api/v1/assets?drama_id=1", None),
    ("GET", "/api/v1/assets?drama_id=2", None),
    ("GET", "/api/v1/assets?type=video", None),
    ("GET", "/api/v1/assets?type=image", None),
    ("GET", "/api/v1/assets?page=1&page_size=2", None),
    ("GET", "/api/v1/assets?page=2&page_size=2", None),
    ("GET", "/api/v1/assets?page_size=999", None),
    ("GET", "/api/v1/assets?page_size=0", None),
    ("GET", "/api/v1/assets?page=abc", None),
    # —— 详情 / 更新 / 删除（全部确定）——
    ("GET", "/api/v1/assets/9801", None),
    ("GET", "/api/v1/assets/abc", None),
    ("GET", "/api/v1/assets/999999", None),
    ("PUT", "/api/v1/assets/9801", {"name": "改名", "category": "道具"}),
    ("PUT", "/api/v1/assets/9801", {}),
    ("PUT", "/api/v1/assets/abc", {"name": "x"}),
    ("PUT", "/api/v1/assets/999999", {"name": "x"}),
    ("GET", "/api/v1/assets/9801", None),
    ("DELETE", "/api/v1/assets/9801", None),
    ("DELETE", "/api/v1/assets/9801", None),
    ("DELETE", "/api/v1/assets/999999", None),
    ("GET", "/api/v1/assets", None),
    # —— import 分支 ——
    # 导入产生的行同样带服务端时间戳，故改用「按 drama_id 过滤」验证导入结果（单条，确定）。
    ("POST", "/api/v1/assets/import/image/999999", None),
    ("POST", "/api/v1/assets/import/video/999999", None),
    ("POST", "/api/v1/assets/import/image/abc", None),
    ("POST", "/api/v1/__seed/image_gen", {"drama_id": 7, "image_url": "http://x/a.png", "local_path": "/s/a.png",
                                          "created_at": "2026-01-01T00:00:00.000Z"}),
    ("POST", "/api/v1/assets/import/image/1", None),
    ("GET", "/api/v1/assets?drama_id=7", None),
    ("POST", "/api/v1/__seed/video_gen", {"drama_id": 8, "video_url": "http://x/a.mp4", "local_path": "/s/a.mp4",
                                          "created_at": "2026-01-01T00:00:00.000Z"}),
    ("POST", "/api/v1/assets/import/video/1", None),
    ("GET", "/api/v1/assets?drama_id=8", None),
]

# upload 对拍：multipart 上传。__file__ 触发 multipart，其余字段作为表单字段。
# 文件名（时间戳+UUID）由 normalize() 归一化为 <name>。
_PNG = {"filename": "a.png", "content": "PNGDATA", "content_type": "image/png"}
_TXT = {"filename": "a.txt", "content": "hello", "content_type": "text/plain"}
_WEBP = {"filename": "b.webp", "content": "WEBP", "content_type": "image/webp"}

CASES += [
    ("POST", "/api/v1/upload/image", None),                       # 无文件 → 400
    ("POST", "/api/v1/upload/image", {"__file__": _TXT}),          # 非白名单 → 500
    ("POST", "/api/v1/upload/image", {"__file__": _PNG}),          # 无 drama_id → uploads/
    ("POST", "/api/v1/upload/image", {"__file__": _WEBP}),         # 扩展名取原文件名
    ("POST", "/api/v1/upload/image", {"__file__": _PNG, "drama_id": "0"}),
    ("POST", "/api/v1/upload/image", {"__file__": _PNG, "drama_id": "abc"}),
    ("POST", "/api/v1/upload/image", {"__file__": _PNG, "drama_id": "999999"}),  # → library/uploads
    ("POST", "/api/v1/__seed/drama", {"title": "对拍剧", "created_at": "2026-01-02T00:00:00.000Z"}),
    ("POST", "/api/v1/upload/image", {"__file__": _PNG, "drama_id": "1"}),       # → projects/0001_…
]

# audio 对拍：TTS 合成。依赖 __seed/tts_config（base_url 指向 TTS stub）+ __seed/episode/storyboard。
# 文件名归一化为 <name>，故只比对路径结构（audio/<name>.mp3）。
CASES += [
    # 无 tts_config 时（在 seed 之前）应报「未配置 TTS」类错误
    ("POST", "/api/v1/audio/extract", {"text": "你好世界"}),
    # 缺少 storyboard_id 与 text
    ("POST", "/api/v1/audio/extract", {}),
    ("POST", "/api/v1/audio/extract/batch", {}),
    ("POST", "/api/v1/audio/extract/batch", {"storyboard_ids": "not-a-list"}),
    # 写入配置 + 剧集 + 分镜
    ("POST", "/api/v1/__seed/tts_config", {"provider": "openai", "api_key": "sk-test",
                                           "base_url": f"http://127.0.0.1:{TTS_STUB_PORT}/v1",
                                           "model": ["tts-1"], "is_default": 1}),
    ("POST", "/api/v1/__seed/episode", {"drama_id": 1, "title": "第1集", "episode_number": 1}),
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "今天天气真好", "narration": "旁白内容"}),
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "", "narration": "只有旁白"}),
    # 单条：直接传 text
    ("POST", "/api/v1/audio/extract", {"text": "直接合成"}),
    # 单条：按 storyboard_id 读 dialogue（对白）
    ("POST", "/api/v1/audio/extract", {"storyboard_id": 1}),
    # 单条：narration 分支
    ("POST", "/api/v1/audio/extract", {"storyboard_id": 2, "tts_kind": "narration"}),
    # 单条：narration 但分镜旁白为空 → 业务 400
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "有对白", "narration": ""}),
    ("POST", "/api/v1/audio/extract", {"storyboard_id": 3, "tts_kind": "narration"}),
    # 单条：dialogue 为空且未传 text → 业务 400
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "", "narration": "旁白"}),
    ("POST", "/api/v1/audio/extract", {"storyboard_id": 4}),
    # batch：含空对白分镜 → 该条返回 error
    ("POST", "/api/v1/audio/extract/batch", {"storyboard_ids": [1, 4, 999999]}),
    ("POST", "/api/v1/audio/extract/batch", {"storyboard_ids": ["abc", 1]}),
]

# images 对拍（同步端点子集）：实际读写 image_generations 表。
# 不含 create / episode-backgrounds-extract（需真实图像生成 API）。
CASES += [
    # 空表
    ("GET", "/api/v1/images?drama_id=1", None),
    # 上传一条记录（backend-node upload 仅建记录，status=completed）
    ("POST", "/api/v1/images/upload", {"drama_id": 1, "prompt": "一个女孩", "provider": "upload"}),
    # 查询 / 详情 / 404
    ("GET", "/api/v1/images/1", None),
    ("GET", "/api/v1/images/999999", None),
    ("GET", "/api/v1/images/abc", None),
    # 软删 + 删除后再查 404 + 重复删除 404
    ("DELETE", "/api/v1/images/1", None),
    ("GET", "/api/v1/images/1", None),
    ("DELETE", "/api/v1/images/1", None),
    # 再 seed 一条（带 url + frame_type），验证过滤
    ("POST", "/api/v1/__seed/image_gen", {"drama_id": 1, "image_url": "http://cdn.example/scene.png",
                                          "local_path": "image/scene.png", "frame_type": "scene"}),
    ("GET", "/api/v1/images?drama_id=1&frame_type=scene", None),
    ("GET", "/api/v1/images?drama_id=1", None),
    # 非数字 drama_id 当 0 → 空
    ("GET", "/api/v1/images?drama_id=abc", None),
    # 给 episode 1 写 scene（带 image_url）+ storyboard（带 scene_id + image_url），验证背景图聚合
    ("POST", "/api/v1/__seed/scene", {"episode_id": 1,
                                      "image_url": "http://cdn.example/sceneA.png",
                                      "storyboard_image_url": "http://cdn.example/sbA.png"}),
    ("GET", "/api/v1/images/episode/1/backgrounds", None),
    ("GET", "/api/v1/images/episode/999999/backgrounds", None),
    ("GET", "/api/v1/images/episode/abc/backgrounds", None),
    # scene 端点：建 image_generation 任务（仅返回 { task_id }），resource_id = scene_id（路径参数）
    ("POST", "/api/v1/images/scene/2", {}),
    ("POST", "/api/v1/images/scene/abc", {}),
    ("POST", "/api/v1/images/scene/999999", {}),
    # episode-batch：恒返回空（POST，:episode_id 纯占位）
    ("POST", "/api/v1/images/episode/1/batch", {}),
    ("POST", "/api/v1/images/episode/abc/batch", {}),
]

# videos 对拍（同步端点子集）：实际读写 video_generations 表。
# 不含 create / resume-poll（需真实视频生成 API）。
CASES += [
    # 空表
    ("GET", "/api/v1/videos?drama_id=1", None),
    # seed 一条 processing
    ("POST", "/api/v1/__seed/video_gen", {"drama_id": 1, "video_url": "http://cdn.example/a.mp4",
                                           "local_path": "video/a.mp4", "status": "processing"}),
    # 详情 / 404
    ("GET", "/api/v1/videos/1", None),
    ("GET", "/api/v1/videos/999999", None),
    ("GET", "/api/v1/videos/abc", None),
    # 软删 + 再查 404 + 重复删除 404
    ("DELETE", "/api/v1/videos/1", None),
    ("GET", "/api/v1/videos/1", None),
    ("DELETE", "/api/v1/videos/1", None),
    # 再 seed 一条 completed，验证 status 过滤
    ("POST", "/api/v1/__seed/video_gen", {"drama_id": 1, "video_url": "http://cdn.example/b.mp4",
                                           "local_path": "video/b.mp4", "status": "completed"}),
    ("GET", "/api/v1/videos?drama_id=1&status=completed", None),
    ("GET", "/api/v1/videos?drama_id=1", None),
    ("GET", "/api/v1/videos?drama_id=abc", None),
    # fromImage：基于图生视频建任务（仅返回 { task_id }）
    ("POST", "/api/v1/videos/image/5", {}),
    ("POST", "/api/v1/videos/image/abc", {}),
    ("POST", "/api/v1/videos/image/999999", {}),
    # episode-batch：恒返回空
    ("POST", "/api/v1/videos/episode/1/batch", {}),
    ("POST", "/api/v1/videos/episode/abc/batch", {}),
]

# video-merges 对拍（同步端点子集）：list / create / get / delete。
CASES += [
    # 空列表
    ("GET", "/api/v1/video-merges?drama_id=1", None),
    # 创建合成任务（建记录 + async_tasks，status=pending）
    ("POST", "/api/v1/video-merges", {"episode_id": 1, "drama_id": 1, "title": "第1集合成",
                                      "provider": "ffmpeg", "scenes": [{"video_url": "http://x/a.mp4", "duration": 3}]}),
    # 详情 / 404
    ("GET", "/api/v1/video-merges/1", None),
    ("GET", "/api/v1/video-merges/999999", None),
    ("GET", "/api/v1/video-merges/abc", None),
    # 软删 + 再查 404 + 重复删除 404
    ("DELETE", "/api/v1/video-merges/1", None),
    ("GET", "/api/v1/video-merges/1", None),
    ("DELETE", "/api/v1/video-merges/1", None),
    # 过滤
    ("POST", "/api/v1/__seed/video_merge", {"episode_id": 1, "drama_id": 1, "title": "已完成",
                                            "status": "completed", "merged_url": "http://cdn.example/m.mp4"}),
    ("GET", "/api/v1/video-merges?episode_id=1", None),
    ("GET", "/api/v1/video-merges?drama_id=1&status=completed", None),
]

# dramas（P4/P5）：合成 / 下载 / 示例。纯 DB / 真实同步；纯 AI 占位端点不在此对拍。
CASES += [
    # 准备：对拍剧 8800（已在主 CASES 列表 seeding）下挂剧集 8801（带 video_url）+ 分镜 8811/8812（带视频）
    ("POST", "/api/v1/__seed/episode", {"id": 8801, "drama_id": 8800, "title": "第1集", "episode_number": 1,
                                        "video_url": "http://cdn.example/ep8801.mp4"}),
    # status 显式给出：MySQL 的 TEXT 列不允许 DEFAULT 值，而 Node(SQLite) 建表为 DEFAULT 'draft'，
    # 若不显式写入会把"数据库默认值差异"误判为移植差异。
    ("POST", "/api/v1/__seed/storyboard", {"id": 8811, "episode_id": 8801, "dialogue": "镜头A",
                                           "video_url": "http://cdn.example/sb8811.mp4", "local_path": "storyboard/sb8811.mp4",
                                           "duration": 4, "status": "draft"}),
    ("POST", "/api/v1/__seed/storyboard", {"id": 8812, "episode_id": 8801, "dialogue": "镜头B",
                                           "video_url": "http://cdn.example/sb8812.mp4", "local_path": "storyboard/sb8812.mp4",
                                           "duration": 5, "status": "draft"}),
    # download-video：成功
    ("GET", "/api/v1/dramas/8800/episodes/8801/download-video", None),
    # download-video：剧集不存在 → 404
    ("GET", "/api/v1/dramas/8800/episodes/999999/download-video", None),
    # download-video：无 video_url → 400
    ("POST", "/api/v1/__seed/episode", {"id": 8802, "drama_id": 8800, "title": "无视频集", "episode_number": 2}),
    ("GET", "/api/v1/dramas/8800/episodes/8802/download-video", None),
    # finalize：有视频分镜 → 建合成任务（message / merge_id / scenes_count / task_id）
    ("PUT", "/api/v1/dramas/8800/episodes/8801/finalize", {"watermark_text": "示例水印"}),
    # finalize：剧集不存在 → 404
    ("PUT", "/api/v1/dramas/8800/episodes/999999/finalize", {}),
    # examples：无 EXAMPLE_DRAMA_PATH 环境变量 → 返回 []
    ("GET", "/api/v1/dramas/examples", None),
]

# episodes（别名路由组）：GET storyboards / finalize / download 为纯 DB；characters/extract 建任务（纯 DB）
CASES += [
    # GET 本集分镜列表（8801 下有 8811/8812，且带 duration）
    ("GET", "/api/v1/episodes/8801/storyboards", None),
    # GET 空集分镜列表 → 空数组
    ("GET", "/api/v1/episodes/8802/storyboards", None),
    # GET 不存在剧集 → 仍返回空（Node 无存在性校验）
    ("GET", "/api/v1/episodes/999999/storyboards", None),
    # download：有 video_url → 200
    ("GET", "/api/v1/episodes/8801/download", None),
    # download：无 video_url → 400
    ("GET", "/api/v1/episodes/8802/download", None),
    # download：剧集不存在 → 404
    ("GET", "/api/v1/episodes/999999/download", None),
    # finalize：有视频分镜 → 建合成任务
    ("POST", "/api/v1/episodes/8801/finalize", {"watermark_text": "示例水印"}),
    # finalize：剧集不存在 → 404
    ("POST", "/api/v1/episodes/999999/finalize", {}),
    # characters/extract：建任务 → 返回 task_id（task_id 动态，被 DYNAMIC_KEYS 归一）
    ("POST", "/api/v1/episodes/8801/characters/extract", None),
]

# generation（角色 / 故事生成）：同步部分为纯 DB，可直接对拍；AI 生成按约定未接入
CASES += [
    # characters：缺 drama_id → 400 'drama_id 必填'
    ("POST", "/api/v1/generation/characters", {}),
    # characters：有 drama_id → 建任务，返回 { task_id, status: 'pending' }
    ("POST", "/api/v1/generation/characters", {"drama_id": 8800}),
    # story：有 drama_id → 建 story_generation 任务
    ("POST", "/api/v1/generation/story", {"drama_id": 8800}),
    # story：同一 drama_id 再次调用 → 复用进行中的任务（task_id 与上一条一致）
    ("POST", "/api/v1/generation/story", {"drama_id": 8800}),
    # story：drama_id 不存在 → 400 '项目不存在'
    ("POST", "/api/v1/generation/story", {"drama_id": 999999}),
    # story：无 drama_id 且无 premise → 500 '请提供故事梗概'（该文案不含 400 关键字）
    ("POST", "/api/v1/generation/story", {}),
]

# POST /images、POST /videos（create）：建任务 + 插入记录，返回 201 记录对象。
# 必须放在 CASES 末尾：Node 的 setImmediate 会真实跑生成并把记录置为 failed，
# 若提前执行会污染前面 images/videos 的 GET 列表用例（Python 无后台处理，状态恒为 pending/processing）。
CASES += [
    ("POST", "/api/v1/images", {"drama_id": 1, "prompt": "夕阳下的城市", "style": "", "provider": "openai", "aspect_ratio": "16:9", "frame_type": "first"}),
    ("POST", "/api/v1/images", {"drama_id": 1, "prompt": "夜景街景", "style": "赛博朋克", "aspect_ratio": "9:16", "frame_type": "last"}),
    ("POST", "/api/v1/images", {"drama_id": 1, "prompt": "", "style": "写实", "size": "1024x1024", "reference_images": ["a.png", "b.png"]}),
    ("POST", "/api/v1/images", {"drama_id": 1, "prompt": "尾帧", "frame_type": "last", "use_first_frame_layout_lock": 0}),
    # 传 last_frame_url 跳过 storyboard 参考图查询（Node 在无 storyboard 行时会抛错）
    ("POST", "/api/v1/videos", {"drama_id": 1, "prompt": "海边奔跑", "style": "", "provider": "chatfire", "last_frame_url": "http://x/last.png", "aspect_ratio": "9:16", "duration": 5, "seed": 42, "camera_fixed": True, "watermark": 0}),
    ("POST", "/api/v1/videos", {"drama_id": 1, "prompt": "雪中行走", "style": "写实", "last_frame_url": "p.png", "aspect_ratio": "横屏"}),
    ("POST", "/api/v1/videos", {"drama_id": 1, "prompt": "竖向视频", "last_frame_url": "v.png", "aspect_ratio": "portrait", "reference_image_urls": ["r1.png"]}),
]

# POST /videos/:id/resume-poll：同步置回 processing（上游轮询在 setImmediate，未移植）。
# 放在末尾：Node 的 setImmediate 会把记录改回 failed，避免污染前面的 GET 用例。
CASES += [
    ("POST", "/api/v1/videos/999999/resume-poll", None),
    ("POST", "/api/v1/videos/abc/resume-poll", None),
    ("POST", "/api/v1/__seed/video_gen_pt", {"id": 9001, "drama_id": 1, "status": "failed", "provider_task_id": "pt-1001", "task_id": None}),
    ("POST", "/api/v1/videos/9001/resume-poll", None),
    ("POST", "/api/v1/__seed/video_gen_pt", {"id": 9002, "drama_id": 1, "status": "failed", "provider_task_id": None}),
    ("POST", "/api/v1/videos/9002/resume-poll", None),
    ("POST", "/api/v1/__seed/video_gen_pt", {"id": 9003, "drama_id": 1, "status": "completed", "provider_task_id": "pt-x"}),
    ("POST", "/api/v1/videos/9003/resume-poll", None),
    ("POST", "/api/v1/__seed/video_gen_pt", {"id": 9004, "drama_id": 1, "status": "processing", "provider_task_id": "pt-y"}),
    ("POST", "/api/v1/videos/9004/resume-poll", None),
]

# POST /images/episode/:id/backgrounds/extract：建 background_extraction 任务（真实提取未移植）。
# 注意：Node 的 setImmediate 会真实跑提取（无 AI key 会置 failed 并删除场景），故放末尾且用独立 episode id。
CASES += [
    ("POST", "/api/v1/__seed/episode", {"id": 9101, "drama_id": 1, "title": "提取测试集", "episode_number": 9101, "script_content": "场景一：咖啡馆内。\n场景二：雨夜街道。", "description": ""}),
    ("POST", "/api/v1/images/episode/9101/backgrounds/extract", {"model": "", "style": "", "language": "zh"}),
    ("POST", "/api/v1/__seed/episode", {"id": 9102, "drama_id": 1, "title": "空剧本集B", "episode_number": 9102, "script_content": "", "description": ""}),
    ("POST", "/api/v1/images/episode/9102/backgrounds/extract", {"model": ""}),
    ("POST", "/api/v1/images/episode/999998/backgrounds/extract", {"model": ""}),
]

# POST /storyboards/:id/upscale：解析本地图 → 2x 超分。
# 种子分镜无磁盘图片（local_path 为 null），故确定性地走 400 '分镜没有本地图片，无法超分'。
# 放在末尾：真实超分会改写 storyboards.local_path，避免污染前面的 GET 用例。
CASES += [
    ("POST", "/api/v1/storyboards/abc/upscale", None),
    ("POST", "/api/v1/storyboards/999997/upscale", None),
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "待超分分镜", "narration": ""}),
    ("POST", "/api/v1/storyboards/1/upscale", None),
]

# POST /storyboards/:id/polish-prompt：仅对拍同步校验分支（404 分镜不存在 / 400 无可优化内容）。
# 成功路径调用 AI（未移植），故不加入对拍。
CASES += [
    ("POST", "/api/v1/storyboards/999996/polish-prompt", {}),
    ("POST", "/api/v1/__seed/storyboard", {"episode_id": 1, "dialogue": "", "narration": ""}),
    ("POST", "/api/v1/storyboards/1/polish-prompt", {}),
]

# SSE 润色端点的同步校验分支（AI 流式返回未移植，故只覆盖 400/404 分支）
CASES += [
    # universal-segment-polish-stream：draft 为空 → 400
    ("POST", "/api/v1/storyboards/1/universal-segment-polish-stream", {"draft_universal_segment_text": ""}),
    ("POST", "/api/v1/storyboards/1/universal-segment-polish-stream", {"draft_universal_segment_text": "   "}),
    ("POST", "/api/v1/storyboards/1/universal-segment-polish-stream", {}),
    # classic-video-prompt-polish-stream：不存在 → 404；universal 模式 → 400
    ("POST", "/api/v1/storyboards/999995/classic-video-prompt-polish-stream", {}),
    ("POST", "/api/v1/__seed/storyboard", {"id": 9501, "episode_id": 1, "dialogue": "d", "narration": "", "creation_mode": "universal"}),
    ("POST", "/api/v1/storyboards/9501/classic-video-prompt-polish-stream", {}),
]

# buildUniversalSegmentUserPromptBundle 的三个校验分支（AI 部分未移植，故只覆盖 400/404）
CASES += [
    # 1) not_found
    ("POST", "/api/v1/storyboards/999994/universal-segment-prompt", {}),
    ("POST", "/api/v1/storyboards/999994/universal-segment-prompt-stream", {}),
    ("POST", "/api/v1/storyboards/999994/universal-segment-polish-stream", {"draft_universal_segment_text": "x"}),
    # 2) bad_request：无参考图槽位（有对白 → lines 非空，slots 为空）
    ("POST", "/api/v1/__seed/storyboard", {"id": 9502, "episode_id": 1, "dialogue": "有对白", "narration": ""}),
    ("POST", "/api/v1/storyboards/9502/universal-segment-prompt", {}),
    ("POST", "/api/v1/storyboards/9502/universal-segment-prompt-stream", {}),
    ("POST", "/api/v1/storyboards/9502/universal-segment-polish-stream", {"draft_universal_segment_text": "草稿"}),
    # 3) bad_request：无任何可用信息（force 跳过参考图校验，且所有文本字段为空）
    ("POST", "/api/v1/__seed/storyboard", {"id": 9503, "episode_id": 1, "dialogue": "", "narration": ""}),
    ("POST", "/api/v1/storyboards/9503/universal-segment-prompt", {"force_without_reference_images": True}),
    ("POST", "/api/v1/storyboards/9503/universal-segment-prompt-stream", {"force_without_reference_images": True}),
    # 注意：润色流不覆盖分支 3 —— universalSegmentOverride=draft 使 CURRENT_UNIVERSAL_SEGMENT 行非空，
    # 故 lines 非空，Node 会继续走 AI（结果依赖外网，不可对拍），故不加该 case。
    # 未 force 时仍走分支 2（参考图校验优先于信息校验）
    ("POST", "/api/v1/storyboards/9503/universal-segment-prompt", {}),
]

# 覆盖度强化：images 列表的真实过滤 + 分页。
# 种子已支持 id / status / frame_type / storyboard_id / prompt，可造出真正命中的数据。
# 注：id / created_at 属 DYNAMIC_KEYS 会被归一化，故列表用例实际校验的是
#     「条目数量 + 非动态字段（frame_type / status / prompt）」，即过滤与分页真正要保证的部分。
CASES += [
    ("POST", "/api/v1/__seed/image_gen", {"id": 9601, "drama_id": 50, "storyboard_id": 8001, "frame_type": "first",
                                          "status": "completed", "prompt": "p1", "image_url": "http://x/1.png",
                                          "local_path": "image/1.png", "created_at": "2026-01-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/image_gen", {"id": 9602, "drama_id": 50, "storyboard_id": 8001, "frame_type": "first",
                                          "status": "pending", "prompt": "p2", "image_url": "http://x/2.png",
                                          "local_path": "image/2.png", "created_at": "2026-01-01T00:00:02.000Z"}),
    ("POST", "/api/v1/__seed/image_gen", {"id": 9603, "drama_id": 50, "storyboard_id": 8002, "frame_type": "last",
                                          "status": "completed", "prompt": "p3", "image_url": "http://x/3.png",
                                          "local_path": "image/3.png", "created_at": "2026-01-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/image_gen", {"id": 9604, "drama_id": 50, "storyboard_id": 8002, "frame_type": "key",
                                          "status": "failed", "prompt": "p4", "image_url": "http://x/4.png",
                                          "local_path": "image/4.png", "created_at": "2026-01-01T00:00:04.000Z"}),
    ("POST", "/api/v1/__seed/image_gen", {"id": 9605, "drama_id": 51, "storyboard_id": 8003, "frame_type": "first",
                                          "status": "completed", "prompt": "p5", "image_url": "http://x/5.png",
                                          "local_path": "image/5.png", "created_at": "2026-01-01T00:00:05.000Z"}),
    # 过滤（可校验：frame_type / status / prompt 非动态字段）
    ("GET", "/api/v1/images?drama_id=50", None),
    ("GET", "/api/v1/images?drama_id=50&frame_type=first", None),
    ("GET", "/api/v1/images?drama_id=50&frame_type=last", None),
    ("GET", "/api/v1/images?drama_id=50&frame_type=nope", None),
    ("GET", "/api/v1/images?drama_id=50&status=completed", None),
    ("GET", "/api/v1/images?drama_id=50&status=pending", None),
    ("GET", "/api/v1/images?drama_id=50&status=failed", None),
    ("GET", "/api/v1/images?drama_id=50&frame_type=first&status=completed", None),
    ("GET", "/api/v1/images?drama_id=50&frame_type=first&status=pending", None),
    ("GET", "/api/v1/images?storyboard_id=8001", None),
    ("GET", "/api/v1/images?storyboard_id=8002", None),
    ("GET", "/api/v1/images?storyboard_id=999998", None),
    ("GET", "/api/v1/images?drama_id=51", None),
    # 分页边界
    ("GET", "/api/v1/images?drama_id=50&page=1&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=50&page=2&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=50&page=3&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=50&page_size=0", None),
    ("GET", "/api/v1/images?drama_id=50&page=0&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=50&page=abc&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=50&page=1&page_size=999", None),
    # 详情命中（种子 id 显式，可稳定读取）
    ("GET", "/api/v1/images/9603", None),
    ("GET", "/api/v1/images/9605", None),
    ("DELETE", "/api/v1/images/9605", None),
    ("GET", "/api/v1/images/9605", None),
    ("GET", "/api/v1/images?drama_id=51", None),
]

# 排序覆盖：此前分页/过滤用例的可见性被 DYNAMIC_KEYS 归一化削弱，排序未被真正校验。
# 关键手法：故意「乱序插入」（插入顺序 s1,s2,s3 对应时间 1,3,2），使插入序 ≠ 时间倒序。
# 若某端漏掉 ORDER BY created_at DESC，会返回插入序 s1,s2,s3 而非正确的 s2,s3,s1，从而被对拍捕获。
# video_url / title 不属于 DYNAMIC_KEYS，故列表顺序可被完整观测。
CASES += [
    # videos：ORDER BY created_at DESC
    ("POST", "/api/v1/__seed/video_gen", {"drama_id": 60, "video_url": "http://cdn.example/s1.mp4",
                                           "local_path": "video/s1.mp4", "created_at": "2026-02-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/video_gen", {"drama_id": 60, "video_url": "http://cdn.example/s2.mp4",
                                           "local_path": "video/s2.mp4", "created_at": "2026-02-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/video_gen", {"drama_id": 60, "video_url": "http://cdn.example/s3.mp4",
                                           "local_path": "video/s3.mp4", "created_at": "2026-02-01T00:00:02.000Z"}),
    ("GET", "/api/v1/videos?drama_id=60", None),
    ("GET", "/api/v1/videos?drama_id=60&page=1&page_size=2", None),
    ("GET", "/api/v1/videos?drama_id=60&page=2&page_size=2", None),
    # video-merges：ORDER BY created_at DESC
    ("POST", "/api/v1/__seed/video_merge", {"episode_id": 6001, "drama_id": 60, "title": "m1",
                                            "status": "completed", "created_at": "2026-02-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/video_merge", {"episode_id": 6001, "drama_id": 60, "title": "m2",
                                            "status": "completed", "created_at": "2026-02-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/video_merge", {"episode_id": 6001, "drama_id": 60, "title": "m3",
                                            "status": "completed", "created_at": "2026-02-01T00:00:02.000Z"}),
    ("GET", "/api/v1/video-merges?episode_id=6001", None),
    ("GET", "/api/v1/video-merges?drama_id=60&status=completed", None),
    # assets：ORDER BY created_at DESC
    # 注：原有 assets 用例用连续 POST 建记录，created_at 由服务端 timestamp()（毫秒）生成，
    # 若两条落在同一毫秒则顺序由 DB 任意决定 → 潜在 flaky。此处改用显式 created_at 种子，既消除
    # 该不确定性，又补上排序覆盖。name 非动态字段，顺序可被完整观测。
    ("POST", "/api/v1/__seed/asset", {"id": 9701, "drama_id": 61, "name": "a1", "type": "image", "created_at": "2026-03-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/asset", {"id": 9702, "drama_id": 61, "name": "a2", "type": "image", "created_at": "2026-03-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/asset", {"id": 9703, "drama_id": 61, "name": "a3", "type": "image", "created_at": "2026-03-01T00:00:02.000Z"}),
    ("POST", "/api/v1/__seed/asset", {"id": 9704, "drama_id": 61, "name": "v1", "type": "video", "created_at": "2026-03-01T00:00:04.000Z"}),
    ("GET", "/api/v1/assets?drama_id=61", None),
    ("GET", "/api/v1/assets?drama_id=61&type=image", None),
    ("GET", "/api/v1/assets?drama_id=61&type=video", None),
    ("GET", "/api/v1/assets?drama_id=61&page=1&page_size=2", None),
    ("GET", "/api/v1/assets?drama_id=61&page=2&page_size=2", None),
    ("GET", "/api/v1/assets/9702", None),
]

# frame-prompts 排序覆盖：这是唯一按 created_at **升序**（ASC）的列表，与其他端点相反，
# 是移植易错点（容易顺手写成 DESC）。保存端点不接受 created_at，故需显式种子才能构造确定数据。
# 手法同上：乱序插入（插入序 f1,f2,f3 对应时间 01,03,02），ASC 正确序为 f1,f3,f2（≠ 插入序），
# 若写成 DESC 或漏掉 ORDER BY 都会被捕获。prompt 非动态字段，顺序可完整观测。
CASES += [
    ("POST", "/api/v1/__seed/storyboard", {"id": 9900, "episode_id": 1, "dialogue": "排序用分镜", "narration": ""}),
    ("POST", "/api/v1/__seed/frame_prompt", {"id": 9901, "storyboard_id": 9900, "frame_type": "first",
                                             "prompt": "f1", "created_at": "2026-05-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/frame_prompt", {"id": 9902, "storyboard_id": 9900, "frame_type": "key",
                                             "prompt": "f2", "created_at": "2026-05-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/frame_prompt", {"id": 9903, "storyboard_id": 9900, "frame_type": "last",
                                             "prompt": "f3", "created_at": "2026-05-01T00:00:02.000Z"}),
    ("GET", "/api/v1/storyboards/9900/frame-prompts", None),
    # 保存（delete-then-insert）：更新 f1 后其 created_at 变为最新，ASC 下应排到末位
    ("PUT", "/api/v1/storyboards/9900/frame-prompts/first", {"prompt": "f1-updated", "description": "d", "layout": "grid(2x2)"}),
    ("GET", "/api/v1/storyboards/9900/frame-prompts", None),
    # 新增一条（POST 保存接口不存在，故用 PUT 新 frame_type）
    ("PUT", "/api/v1/storyboards/9900/frame-prompts/panel", {"prompt": "f4", "description": None, "layout": None}),
    ("GET", "/api/v1/storyboards/9900/frame-prompts", None),
    # 空分镜
    ("POST", "/api/v1/__seed/storyboard", {"id": 9904, "episode_id": 1, "dialogue": "空帧分镜", "narration": ""}),
    ("GET", "/api/v1/storyboards/9904/frame-prompts", None),
]

# images 列表排序覆盖（DESC 非平凡性）：与上面的 videos/video-merges 同构。
# images 的 id / created_at 属 DYNAMIC_KEYS 被归一化，但 image_url 不是，可完整观测顺序。
# 乱序插入（插入序 i1,i2,i3 对应时间 1,3,2），DESC 正确序为 i2,i3,i1，捕获漏写 ORDER BY。
CASES += [
    ("POST", "/api/v1/__seed/image_gen", {"id": 9801, "drama_id": 70, "image_url": "http://cdn.example/i1.png",
                                          "local_path": "image/i1.png", "status": "completed", "frame_type": "first",
                                          "created_at": "2026-06-01T00:00:01.000Z"}),
    ("POST", "/api/v1/__seed/image_gen", {"id": 9802, "drama_id": 70, "image_url": "http://cdn.example/i2.png",
                                          "local_path": "image/i2.png", "status": "completed", "frame_type": "last",
                                          "created_at": "2026-06-01T00:00:03.000Z"}),
    ("POST", "/api/v1/__seed/image_gen", {"id": 9803, "drama_id": 70, "image_url": "http://cdn.example/i3.png",
                                          "local_path": "image/i3.png", "status": "completed", "frame_type": "key",
                                          "created_at": "2026-06-01T00:00:02.000Z"}),
    ("GET", "/api/v1/images?drama_id=70", None),
    ("GET", "/api/v1/images?drama_id=70&page=1&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=70&page=2&page_size=2", None),
    ("GET", "/api/v1/images?drama_id=70&status=completed", None),
]

# 纯 AI 端点（regenerate-layout-description / rebuild-video-prompt / split-by-audio）契约覆盖。
# 同步分支：非法 id → 400；分镜不存在 → 404。存在时双端均因未移植 AI/重型逻辑返回 500，契约一致。
# 注：三者在 Node 探针中已挂 handler；Python 已移植校验分支并以 NotImplementedError→500 对齐。
CASES += [
    ("POST", "/api/v1/storyboards/abc/regenerate-layout-description", None),
    ("POST", "/api/v1/storyboards/99999/regenerate-layout-description", None),
    ("POST", "/api/v1/storyboards/1/regenerate-layout-description", None),
    ("POST", "/api/v1/storyboards/abc/rebuild-video-prompt", None),
    ("POST", "/api/v1/storyboards/99999/rebuild-video-prompt", None),
    ("POST", "/api/v1/storyboards/1/rebuild-video-prompt", None),
    ("POST", "/api/v1/storyboards/abc/split-by-audio", None),
    ("POST", "/api/v1/storyboards/99999/split-by-audio", None),
    ("POST", "/api/v1/storyboards/1/split-by-audio", None),
]

DYNAMIC_KEYS = {"timestamp", "id", "created_at", "updated_at", "deleted_at", "completed_at", "task_id"}


# 上传 / TTS 生成的文件名含时间戳或 UUID，两端必然不同，归一化后比对路径结构
_UPLOAD_NAME_RE = re.compile(
    r"\d{8}T\d{6}_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|tts_sb(?:x|\d+)_[0-9a-f]{8}"   # TTS 音频：tts_sb<id>_<uuid8>.mp3 或 tts_sbx_<uuid8>.mp3
)


def normalize(obj):
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items() if k not in DYNAMIC_KEYS}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    if isinstance(obj, str):
        return _UPLOAD_NAME_RE.sub("<name>", obj)
    return obj


def split_upload(body):
    """把 case 体拆成 (file_spec, form_fields)；无 __file__ 时返回 (None, body)。"""
    if not isinstance(body, dict) or "__file__" not in body:
        return None, body
    spec = body["__file__"]
    rest = {k: v for k, v in body.items() if k != "__file__"}
    return spec, rest


def http_parts(spec, rest):
    files = None
    if spec is not None:
        files = {"file": (spec["filename"], spec["content"].encode("utf-8"), spec["content_type"])}
    data = rest or None
    return files, data


def call_http(method: str, path: str, body):
    spec, rest = split_upload(body)
    if spec is None:
        # 常规 JSON 用例（保持原有行为）
        r = requests.request(method, BASE + path, json=rest, timeout=15)
        return r.status_code, r.json()
    files, data = http_parts(spec, rest)
    r = requests.request(method, BASE + path, files=files, data=data, timeout=15)
    return r.status_code, r.json()


_PY_CLIENT = None


def init_py() -> None:
    """初始化 Python 端：建表 + 清空测试数据，保证与 Node 内存库同样从空库开始。"""
    global _PY_CLIENT
    from fastapi.testclient import TestClient

    from app.db import session as dbm
    from app.db.schema import ensure_schema
    from app.main import app
    from app.services import promptI18n

    dbm.init_engine()
    with dbm.engine.begin() as conn:
        ensure_schema(conn)
        for t in (
            "async_tasks",
            "assets",
            "images",
            "image_generations",
            "video_generations",
            "video_merges",
            "ai_service_configs",
            "prompt_overrides",
            "ai_model_map",
            "character_libraries",
            "scene_libraries",
            "prop_libraries",
            "episode_characters",
            "storyboard_props",
            "storyboards",
            "storyboard_characters",
            "frame_prompts",
            "scenes",
            "props",
            "characters",
            "episodes",
            "dramas",
        ):
            # TRUNCATE 而非 DELETE：重置 AUTO_INCREMENT，使两端自增 id 同步
            conn.execute(__import__("sqlalchemy").text(f"TRUNCATE TABLE `{t}`"))
    promptI18n._override_cache.clear()

    # 上传落盘目录指向临时目录：响应体只含相对路径 + base_url，故不影响契约对拍，
    # 同时避免污染 backend-node/data/storage。
    from app.api.v1 import upload as v1_upload

    _tmp_storage = tempfile.mkdtemp(prefix="lmd-upload-")
    v1_upload.init_config(
        {"storage": {"local_path": _tmp_storage, "base_url": "http://localhost:5679/static"}}
    )

    _PY_CLIENT = TestClient(app)
    _PY_CLIENT.__enter__()


def seed_py(path: str, body: dict | None) -> tuple[int, dict]:
    """Python 侧 __seed/* 的等价实现（Node 侧由 node_probe.js 提供同名端点）。

    直接写库而非走 HTTP：Python 版没有这些生产端点，仅为让两端从相同数据出发。
    """
    from sqlalchemy import text

    from app.core.response import timestamp
    from app.db import session as dbm

    b = body or {}
    at = b.get("created_at") or timestamp()

    if path == "/api/v1/__seed/task":
        with dbm.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO async_tasks "
                    "(id, type, status, progress, message, resource_id, created_at, updated_at) "
                    "VALUES (:id, :type, :status, :progress, '', :resource_id, :created_at, :updated_at)"
                ),
                {
                    "id": b.get("id"),
                    "type": b.get("type") or "test",
                    "status": b.get("status") or "pending",
                    "progress": b.get("progress") if b.get("progress") is not None else 0,
                    "resource_id": b.get("resource_id") or "",
                    "created_at": at,
                    "updated_at": at,
                },
            )
        return 200, {"success": True, "data": {"id": b.get("id")}}

    if path == "/api/v1/__seed/video_merge":
        with dbm.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO video_merges "
                    "(episode_id, drama_id, title, provider, status, merged_url, task_id, created_at) "
                    "VALUES (:e, :d, :t, :p, :s, :mu, :tid, :at)"
                ),
                {
                    "e": b.get("episode_id"),
                    "d": b.get("drama_id"),
                    "t": b.get("title"),
                    "p": b.get("provider") or "ffmpeg",
                    "s": b.get("status") or "pending",
                    "mu": b.get("merged_url"),
                    "tid": b.get("task_id"),
                    "at": at,
                },
            )
            new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": new_id}}

    if path == "/api/v1/__seed/episode":
        with dbm.engine.begin() as conn:
            eid = b.get("id")
            vurl = b.get("video_url")
            if eid is not None:
                conn.execute(
                    text("INSERT INTO episodes (id, drama_id, title, episode_number, script_content, description, video_url) VALUES (:i, :d, :t, :n, :s, :desc, :v)"),
                    {"i": eid, "d": b.get("drama_id"), "t": b.get("title") or "第1集", "n": b.get("episode_number") or 1,
                     "s": b.get("script_content") or None, "desc": b.get("description") or None, "v": vurl},
                )
                new_id = eid
            else:
                conn.execute(
                    text("INSERT INTO episodes (drama_id, title, episode_number, script_content, description, video_url) VALUES (:d, :t, :n, :s, :desc, :v)"),
                    {"d": b.get("drama_id"), "t": b.get("title") or "第1集", "n": b.get("episode_number") or 1,
                     "s": b.get("script_content") or None, "desc": b.get("description") or None, "v": vurl},
                )
                new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": new_id}}

    if path == "/api/v1/__seed/storyboard":
        sid = b.get("id")
        cm = b.get("creation_mode")
        vurl = b.get("video_url")
        lp = b.get("local_path")
        dur = b.get("duration") if b.get("duration") is not None else 5
        st = b.get("status")
        with dbm.engine.begin() as conn:
            if sid is not None:
                conn.execute(
                    text("INSERT INTO storyboards (id, episode_id, dialogue, narration, creation_mode, video_url, local_path, duration, status, updated_at) VALUES (:i, :e, :d, :n, :c, :v, :lp, :dur, :st, :c2)"),
                    {"i": sid, "e": b.get("episode_id"), "d": b.get("dialogue"), "n": b.get("narration"), "c": cm,
                     "v": vurl, "lp": lp, "dur": dur, "st": st, "c2": timestamp()},
                )
                new_id = sid
            else:
                conn.execute(
                    text("INSERT INTO storyboards (episode_id, dialogue, narration, creation_mode, video_url, local_path, duration, status, updated_at) VALUES (:e, :d, :n, :c, :v, :lp, :dur, :st, :c2)"),
                    {"e": b.get("episode_id"), "d": b.get("dialogue"), "n": b.get("narration"), "c": cm,
                     "v": vurl, "lp": lp, "dur": dur, "st": st, "c2": timestamp()},
                )
                new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": new_id}}

    if path == "/api/v1/__seed/scene":
        eid = b.get("id")
        with dbm.engine.begin() as conn:
            if eid is not None:
                conn.execute(
                    text(
                        "INSERT INTO scenes (id, drama_id, episode_id, image_url, local_path, status) "
                        "VALUES (:id, :d, :e, :iu, :lp, :st)"
                    ),
                    {
                        "id": eid,
                        "d": b.get("drama_id") if b.get("drama_id") is not None else 1,
                        "e": b.get("episode_id"),
                        "iu": b.get("image_url"),
                        "lp": b.get("local_path"),
                        "st": b.get("status") if b.get("status") is not None else "draft",
                    },
                )
                sid = eid
            else:
                conn.execute(
                    text(
                        "INSERT INTO scenes (drama_id, episode_id, image_url, local_path, status) "
                        "VALUES (:d, :e, :iu, :lp, :st)"
                    ),
                    {
                        "d": b.get("drama_id") if b.get("drama_id") is not None else 1,
                        "e": b.get("episode_id"),
                        "iu": b.get("image_url"),
                        "lp": b.get("local_path"),
                        "st": b.get("status") if b.get("status") is not None else "draft",
                    },
                )
                sid = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            sb_id = None
            if b.get("storyboard_image_url") is not None or b.get("storyboard_local_path") is not None:
                conn.execute(
                    text(
                        "INSERT INTO storyboards (episode_id, scene_id, image_url, local_path) "
                        "VALUES (:e, :s, :iu, :lp)"
                    ),
                    {
                        "e": b.get("episode_id"),
                        "s": sid,
                        "iu": b.get("storyboard_image_url"),
                        "lp": b.get("storyboard_local_path"),
                    },
                )
                sb_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"scene_id": sid, "storyboard_id": sb_id}}

    if path == "/api/v1/__seed/character":
        eid = b.get("id")
        with dbm.engine.begin() as conn:
            if eid is not None:
                conn.execute(
                    text(
                        "INSERT INTO characters (id, drama_id, name, image_url, local_path, appearance) "
                        "VALUES (:id, :d, :n, :iu, :lp, :ap)"
                    ),
                    {
                        "id": eid,
                        "d": b.get("drama_id") if b.get("drama_id") is not None else 1,
                        "n": b.get("name") or "角色",
                        "iu": b.get("image_url") or "",
                        "lp": b.get("local_path"),
                        "ap": b.get("appearance") or "外貌描述",
                    },
                )
                cid = eid
            else:
                conn.execute(
                    text(
                        "INSERT INTO characters (drama_id, name, image_url, local_path, appearance) "
                        "VALUES (:d, :n, :iu, :lp, :ap)"
                    ),
                    {
                        "d": b.get("drama_id") if b.get("drama_id") is not None else 1,
                        "n": b.get("name") or "角色",
                        "iu": b.get("image_url") or "",
                        "lp": b.get("local_path"),
                        "ap": b.get("appearance") or "外貌描述",
                    },
                )
                cid = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": cid}}

    if path == "/api/v1/__seed/character-library":
        eid = b.get("id")
        with dbm.engine.begin() as conn:
            if eid is not None:
                conn.execute(
                    text(
                        "INSERT INTO character_libraries (id, drama_id, name, category, image_url, local_path, "
                        "description, source_type, source_id, created_at, updated_at) "
                        "VALUES (:id, :d, :n, :c, :iu, :lp, :de, :st, :si, :ca, :ca)"
                    ),
                    {
                        "id": eid,
                        "d": b.get("drama_id"),
                        "n": b.get("name") or "库项",
                        "c": b.get("category"),
                        "iu": b.get("image_url") or "",
                        "lp": b.get("local_path"),
                        "de": b.get("description"),
                        "st": b.get("source_type") or "character",
                        "si": b.get("source_id"),
                        "ca": timestamp(),
                    },
                )
                lid = eid
            else:
                conn.execute(
                    text(
                        "INSERT INTO character_libraries (drama_id, name, category, image_url, local_path, "
                        "description, source_type, source_id, created_at, updated_at) "
                        "VALUES (:d, :n, :c, :iu, :lp, :de, :st, :si, :ca, :ca)"
                    ),
                    {
                        "d": b.get("drama_id"),
                        "n": b.get("name") or "库项",
                        "c": b.get("category"),
                        "iu": b.get("image_url") or "",
                        "lp": b.get("local_path"),
                        "de": b.get("description"),
                        "st": b.get("source_type") or "character",
                        "si": b.get("source_id"),
                        "ca": timestamp(),
                    },
                )
                lid = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": lid}}

    # 注意：Python 的 ai_service_configs 较 Node 多一列 api_protocol（NOT NULL 无默认），必须显式给 ''
    if path == "/api/v1/__seed/tts_config":
        with dbm.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ai_service_configs "
                    "(service_type, provider, api_protocol, name, base_url, api_key, model, default_model, "
                    " priority, is_default, is_active, settings, created_at, updated_at) "
                    "VALUES ('tts', :p, '', 'TTS', :base, 'sk-tts', '[\"tts-1\"]', :dm, 0, 1, :active, :s, "
                    "        '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')"
                ),
                {
                    "p": b.get("provider") or "openai",
                    "base": b.get("base_url") or "",
                    "dm": b.get("default_model") or "tts-1",
                    "active": 1 if b.get("is_active") is None else b["is_active"],
                    "s": b.get("settings"),
                },
            )
            new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": new_id}}

    if path == "/api/v1/__seed/drama":
        at = b.get("created_at") or timestamp()
        eid = b.get("id")
        if eid is not None:
            with dbm.engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO dramas (id, title, created_at, updated_at) VALUES (:id, :t, :c, :c)"),
                    {"id": eid, "t": b.get("title") or "对拍剧", "c": at},
                )
            return 200, {"success": True, "data": {"id": eid}}
        with dbm.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO dramas (title, created_at, updated_at) VALUES (:t, :c, :c)"),
                {"t": b.get("title") or "对拍剧", "c": at},
            )
            new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return 200, {"success": True, "data": {"id": new_id}}

    if path == "/api/v1/__seed/image_gen":
        eid = b.get("id")
        if eid is not None:
            sql = (
                "INSERT INTO image_generations (id, drama_id, storyboard_id, image_url, "
                "local_path, status, frame_type, prompt, created_at, updated_at) "
                "VALUES (:id, :drama_id, :storyboard_id, :image_url, :local_path, "
                ":status, :frame_type, :prompt, :created_at, :updated_at)"
            )
            new_id = eid
        else:
            sql = (
                "INSERT INTO image_generations (drama_id, storyboard_id, image_url, "
                "local_path, status, frame_type, prompt, created_at, updated_at) "
                "VALUES (:drama_id, :storyboard_id, :image_url, :local_path, "
                ":status, :frame_type, :prompt, :created_at, :updated_at)"
            )
            new_id = None
        params = {
            "id": eid,
            "drama_id": b.get("drama_id"),
            "storyboard_id": b.get("storyboard_id"),
            "image_url": b.get("image_url") or "",
            "local_path": b.get("local_path"),
            "status": b.get("status"),
            "frame_type": b.get("frame_type"),
            "prompt": b.get("prompt"),
            "created_at": at,
            "updated_at": at,
        }
        if eid is not None:
            with dbm.engine.begin() as conn:
                conn.execute(text(sql), params)
            return 200, {"success": True, "data": {"id": new_id}}
    elif path == "/api/v1/__seed/video_gen":
        sql = (
            "INSERT INTO video_generations (drama_id, video_url, local_path, created_at) "
            "VALUES (:drama_id, :video_url, :local_path, :created_at)"
        )
        params = {
            "drama_id": b.get("drama_id"),
            "video_url": b.get("video_url") or "",
            "local_path": b.get("local_path"),
            "created_at": at,
        }
    elif path == "/api/v1/__seed/video_gen_pt":
        eid = b.get("id")
        if eid is not None:
            sql = (
                "INSERT INTO video_generations (id, drama_id, video_url, local_path, status, "
                "provider_task_id, task_id, created_at, updated_at) "
                "VALUES (:id, :drama_id, :video_url, :local_path, :status, :provider_task_id, "
                ":task_id, :created_at, :updated_at)"
            )
            new_id = eid
        else:
            sql = (
                "INSERT INTO video_generations (drama_id, video_url, local_path, status, "
                "provider_task_id, task_id, created_at, updated_at) "
                "VALUES (:drama_id, :video_url, :local_path, :status, :provider_task_id, "
                ":task_id, :created_at, :updated_at)"
            )
            new_id = None
        params = {
            "id": eid,
            "drama_id": b.get("drama_id"),
            "video_url": b.get("video_url") or "",
            "local_path": b.get("local_path"),
            "status": b.get("status"),
            "provider_task_id": b.get("provider_task_id"),
            "task_id": b.get("task_id"),
            "created_at": at,
            "updated_at": at,
        }
        if eid is not None:
            with dbm.engine.begin() as conn:
                conn.execute(text(sql), params)
            return 200, {"success": True, "data": {"id": new_id}}
    elif path == "/api/v1/__seed/asset":
        eid = b.get("id")
        ts = b.get("created_at") or at
        if eid is not None:
            sql = (
                "INSERT INTO assets (id, drama_id, name, type, category, url, local_path, "
                "duration, created_at, updated_at) "
                "VALUES (:id, :drama_id, :name, :type, :category, :url, :local_path, "
                ":duration, :created_at, :updated_at)"
            )
            new_id = eid
        else:
            sql = (
                "INSERT INTO assets (drama_id, name, type, category, url, local_path, "
                "duration, created_at, updated_at) "
                "VALUES (:drama_id, :name, :type, :category, :url, :local_path, "
                ":duration, :created_at, :updated_at)"
            )
            new_id = None
        params = {
            "id": eid,
            "drama_id": b.get("drama_id"),
            "name": b.get("name") or "未命名",
            "type": b.get("type") or "image",
            "category": b.get("category"),
            "url": b.get("url") or "",
            "local_path": b.get("local_path"),
            "duration": b.get("duration"),
            "created_at": ts,
            "updated_at": ts,
        }
        if eid is not None:
            with dbm.engine.begin() as conn:
                conn.execute(text(sql), params)
            return 200, {"success": True, "data": {"id": new_id}}
    elif path == "/api/v1/__seed/frame_prompt":
        eid = b.get("id")
        ts = b.get("created_at") or at
        if eid is not None:
            sql = (
                "INSERT INTO frame_prompts (id, storyboard_id, frame_type, prompt, "
                "description, layout, created_at, updated_at) "
                "VALUES (:id, :storyboard_id, :frame_type, :prompt, :description, "
                ":layout, :created_at, :updated_at)"
            )
            new_id = eid
        else:
            sql = (
                "INSERT INTO frame_prompts (storyboard_id, frame_type, prompt, "
                "description, layout, created_at, updated_at) "
                "VALUES (:storyboard_id, :frame_type, :prompt, :description, "
                ":layout, :created_at, :updated_at)"
            )
            new_id = None
        params = {
            "id": eid,
            "storyboard_id": b.get("storyboard_id"),
            "frame_type": b.get("frame_type") or "first",
            "prompt": b.get("prompt") or "",
            "description": b.get("description"),
            "layout": b.get("layout"),
            "created_at": ts,
            "updated_at": ts,
        }
        if eid is not None:
            with dbm.engine.begin() as conn:
                conn.execute(text(sql), params)
            return 200, {"success": True, "data": {"id": new_id}}
    elif path == "/api/v1/__seed/prop":
        eid = b.get("id")
        if eid is not None:
            sql = (
                "INSERT INTO props (id, drama_id, episode_id, name, type, description, prompt, "
                "image_url, local_path, created_at, updated_at) "
                "VALUES (:id, :drama_id, :episode_id, :name, :type, :description, :prompt, "
                ":image_url, :local_path, :created_at, :updated_at)"
            )
            new_id = eid
        else:
            sql = (
                "INSERT INTO props (drama_id, episode_id, name, type, description, prompt, "
                "image_url, local_path, created_at, updated_at) "
                "VALUES (:drama_id, :episode_id, :name, :type, :description, :prompt, "
                ":image_url, :local_path, :created_at, :updated_at)"
            )
            new_id = None
        params = {
            "id": eid,
            "drama_id": b.get("drama_id") if b.get("drama_id") is not None else 1,
            "episode_id": b.get("episode_id"),
            "name": b.get("name") or "道具",
            "type": b.get("type"),
            "description": b.get("description"),
            "prompt": b.get("prompt"),
            "image_url": b.get("image_url") or "",
            "local_path": b.get("local_path"),
            "created_at": at,
            "updated_at": at,
        }
        if eid is not None:
            with dbm.engine.begin() as conn:
                conn.execute(text(sql), params)
            return 200, {"success": True, "data": {"id": new_id}}
    else:
        raise ValueError(f"unknown seed endpoint: {path}")

    with dbm.engine.begin() as conn:
        conn.execute(text(sql), params)
        new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return 200, {"success": True, "data": {"id": new_id}}


def call_py(method: str, path: str, body):
    if path.startswith("/api/v1/__seed/"):
        return seed_py(path, body)
    spec, rest = split_upload(body)
    if spec is None:
        r = _PY_CLIENT.request(method, path, json=rest)
        return r.status_code, r.json()
    files, data = http_parts(spec, rest)
    r = _PY_CLIENT.request(method, path, files=files, data=data)
    return r.status_code, r.json()


class _TTSStubHandler(BaseHTTPRequestHandler):
    """本地 TTS 桩：任何 POST 都返回固定 MP3 字节。

    Node 的 ttsService 用 http.request 直连，Python 用 httpx；
    把 tts 配置的 base_url 指向本桩，两端即可在无需真实密钥的情况下走通成功路径。
    """

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(_FAKE_MP3)))
        self.end_headers()
        self.wfile.write(_FAKE_MP3)

    def log_message(self, *args):
        pass


def _start_tts_stub(port: int) -> HTTPServer:
    srv = HTTPServer(("127.0.0.1", port), _TTSStubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _assert_port_free(port: int, who: str) -> None:
    """启动前置校验：端口已被占用多半意味着上一次运行被中断后残留了旧进程。

    旧探针持有的是**陈旧的内存 SQLite**，若新探针启动失败而请求仍打到旧进程上，
    会出现大面积 DIFF（假阳性），且极难定位。与其给出误导性结果，不如直接报错。
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(
                f"端口 {port} 已被占用（{who}）。通常是上一次运行被中断后残留了进程，"
                f"它持有陈旧的内存数据会导致大量假阳性 DIFF。请先结束占用该端口的进程再重跑。"
            )


def main() -> int:
    _assert_port_free(NODE_PORT, "node_probe")
    tts_stub = _start_tts_stub(TTS_STUB_PORT)
    # 清空 NODE_OPTIONS：某些 IDE 会向其中注入 --require <扩展 shim>，
    # 该 shim 路径不存在或扩展正在重载时，node 会以
    # "Cannot find module ... 4.11.36953988 ..." 直接退出，导致探针无法启动（与被测代码无关）。
    probe_env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    proc = subprocess.Popen(
        ["node", str(ROOT / "tools" / "node_probe.js"), str(NODE_PORT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=probe_env,
    )
    try:
        init_py()
        # 等待探针就绪
        deadline = time.time() + 30
        ready = False
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("PROBE_READY"):
                ready = True
                break
        if not ready:
            print(proc.stderr.read())
            print("node probe failed to start")
            return 2

        diffs = 0
        for idx, (method, path, body) in enumerate(CASES):
            try:
                ns, nb = call_http(method, path, body)
            except Exception as e:  # noqa: BLE001
                print(f"\n[NODE-ERR] #{idx} {method} {path} body={json.dumps(body, ensure_ascii=False)[:200]}: {e}")
                diffs += 1
                continue
            try:
                ps, pb = call_py(method, path, body)
            except Exception as e:  # noqa: BLE001
                print(f"\n[PY-ERR] #{idx} {method} {path} body={json.dumps(body, ensure_ascii=False)[:200]}: {e}")
                diffs += 1
                continue
            nn, pn = normalize(nb), normalize(pb)
            if ns != ps or nn != pn:
                diffs += 1
                print(f"\n[DIFF] #{idx} {method} {path} body={json.dumps(body, ensure_ascii=False)}")
                print(f"  node: status={ns} body={json.dumps(nn, ensure_ascii=False)[:600]}")
                print(f"  py  : status={ps} body={json.dumps(pn, ensure_ascii=False)[:600]}")
        print(f"\nCASES={len(CASES)} DIFFS={diffs}")
        return 1 if diffs else 0
    finally:
        tts_stub.shutdown()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
