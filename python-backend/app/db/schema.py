"""数据库表结构与 DDL 生成系统（统一支持 SQLite 与 MySQL）。

【领域数据建模架构】
1. 核心创作实体模型（Core Entities）：
   - dramas: 短剧项目主表，管理题材、风格预设、元数据、总集数与剧集状态。
   - episodes: 单集剧本表，包含剧本内容、标题、单集视频合成产物与缩略图。
   - characters: 角色表，包含外观、性格、音色、四视图、Seedance2 数字资产、连续性锚点与阶段外貌。
   - scenes: 场景表，包含地点、时间、环境提示词、多视图参考与模型映射。
   - props: 道具表，包含道具描述、提示词、参考图与遮罩。
   - storyboards: 镜头分镜表，承载景别、镜头运镜、横纵视角、对白/旁白、首尾帧与生成状态。
   - frame_prompts: 分镜关键帧提示词（首帧、关键帧、尾帧、九宫格等）。
   - storyboard_characters / storyboard_props / episode_characters: 关联多对多映射表。

2. 生成与媒体资产模型（Generations & Assets）：
   - ai_service_configs: AI 厂商/模型接入配置（支持 OpenAI、DeepSeek、Ark、Kling、Jimeng、ComfyUI 等）。
   - ai_model_map: 场景化模型精准路由映射表（为不同子任务绑定指定模型）。
   - image_generations / video_generations / audio_generations: 图像、视频、音频生成记录与轮询跟踪。
   - video_merges: 分集视频合并任务与音视频合成参数记录。
   - assets: 媒体素材库（集中管理生成的图片、音频、视频、数字人资产）。
   - character_libraries / scene_libraries / prop_libraries: 跨项目的通用公共资产库。
   - prompt_overrides / image_proxy_cache / global_settings: 提示词覆盖热更新、图片代理缓存与全局配置。

3. 高级平台与多 Agent 架构模型（Platform & Multi-Agent Architecture）：
   - prompt_templates / prompt_runs: 提示词模板版本管理与模型调用性能/成本链路追踪。
   - skills / skill_versions: 编排能力技能库与契约声明（输入输出 Schema、模型策略、质量检查）。
   - context_snapshots / memory_items: 上下文切片快照与分剧向量记忆库。
   - workflow_runs / workflow_steps: 工作流 DAG 编排运行实例与执行步骤状态。
   - queue_jobs / worker_nodes: 分布式异步持久化任务队列与 Worker 节点心跳调度。
   - character_voice_profiles / music_bibles / music_cues: 音频设计、配乐 Bible 与分镜配乐 Cue 表。
   - quality_reports: 剧本与分镜质量评估打分报告。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text

# 长文本列统一用 MEDIUMTEXT（超过 TEXT 64KB 限制的列）
LONG_COLUMNS = {
    "script_content", "metadata", "settings", "result",
    "prompt", "image_prompt", "video_prompt", "polished_prompt",
    "negative_prompt", "reference_images", "reference_image_urls",
    "scenes", "merge_options", "continuity_snapshot",
    "identity_anchors", "color_palette", "stages",
    "seedance2_asset", "seedance2_voice_asset",
    "template", "input_schema", "output_schema", "variables",
    "context_snapshot", "final_prompt", "raw_output", "parsed_output",
    "input_payload", "output_payload", "payload", "user_request", "state",
    "content", "summary", "source_refs", "prompt_keys",
    "context_policy", "model_policy", "quality_checks", "examples",
    "memory_refs", "keywords", "error",
    "voice_prompt", "emotion_rules", "negative_traits", "overall_style",
    "theme_prompt", "instruments", "bpm_range", "emotional_palette",
    "mixing_rules", "bgm_prompt", "sfx_prompt", "issues", "suggestions",
    "raw_report", "queues", "ast_blocks", "radar_scores", "growth_chain", "current_status",
}


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # sqlite 语义类型: INTEGER / REAL / TEXT
    extra: str = ""  # 附加 SQL（NOT NULL DEFAULT ... 等）
    comment: str = ""  # MySQL 字段注释；SQLite 建表时自动剔除。


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: str = "id"
    unique: tuple[str, ...] = ()
    indexes: tuple[str, ...] = ()


# TEXT 列作主键/唯一索引/普通索引时 MySQL 不允许，必须转 VARCHAR
# id → async_tasks.id（UUID 36 字符）；key → prompt_overrides/ai_model_map/global_settings 的短 key
# cache_key → image_proxy_cache 的缓存键；resource_id → async_tasks.resource_id（被普通索引）
VARCHAR_OVERRIDES = {
    "id": 64,
    "key": 255,
    "cache_key": 255,
    "resource_id": 512,
    "prompt_key": 128,
    "skill_key": 128,
    "agent_name": 128,
    "workflow_run_id": 64,
    "workflow_step_id": 64,
    "prompt_run_id": 64,
    "step_key": 128,
    "status": 64,
    "type": 64,
    "scope": 64,
    "scope_id": 64,
    "scope_type": 64,
    "memory_type": 64,
    "source_type": 64,
    "character_id": 64,
    "storyboard_id": 64,
    "generation_type": 64,
    "cue_type": 64,
    "report_type": 64,
    "queue_name": 64,
    "task_type": 128,
    "async_task_id": 64,
    "locked_by": 128,
    "worker_id": 128,
    "hostname": 255,
}


def _sqltype(c: Column) -> str:
    if c.type == "INTEGER":
        return "BIGINT"
    if c.type == "REAL":
        return "DOUBLE"
    if c.name in VARCHAR_OVERRIDES:
        return f"VARCHAR({VARCHAR_OVERRIDES[c.name]})"
    # TEXT
    return "MEDIUMTEXT" if c.name in LONG_COLUMNS else "TEXT"


def _strip_text_default(extra: str) -> str:
    """MySQL 8 不允许 TEXT/BLOB 列带 DEFAULT，剔除 DEFAULT 子句（保留 NOT NULL）。"""
    return re.sub(r"\s*DEFAULT\s+(?:'[^']*'|[0-9]+(?:\.[0-9]+)?)", "", extra).strip()


def build_create_sql(t: Table) -> str:
    cols = []
    for c in t.columns:
        st = _sqltype(c)
        extra = c.extra
        if st in ("TEXT", "MEDIUMTEXT"):
            extra = _strip_text_default(extra)
        comment_sql = f" COMMENT '{c.comment.replace(chr(39), chr(39) * 2)}'" if c.comment else ""
        if t.primary_key and c.name == t.primary_key:
            cols.append(f"  `{c.name}` {st} NOT NULL AUTO_INCREMENT PRIMARY KEY" if st == "BIGINT" else f"  `{c.name}` {st} PRIMARY KEY")
        else:
            cols.append(f"  `{c.name}` {st} {extra}{comment_sql}".rstrip())
    pk = t.primary_key
    if pk and "," in pk:  # 仅复合主键需要表级 PRIMARY KEY（单列主键已内联）
        cols.append(f"  PRIMARY KEY ({', '.join('`' + p + '`' for p in pk.split(','))})")
    body = ",\n".join(cols)
    sql = f"CREATE TABLE IF NOT EXISTS `{t.name}` (\n{body}\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    return sql


# ---------------- 23 张表（最终形态） ----------------

TABLES: list[Table] = [
    Table("dramas", (
        Column("id", "INTEGER", comment="短剧项目唯一主键 ID"),
        Column("title", "TEXT", "NOT NULL DEFAULT ''", "剧名/暂定剧名"),
        Column("description", "TEXT", comment="剧情梗概与受众画像简介"),
        Column("genre", "TEXT", comment="题材分类（如都市爽剧/战神归来/悬疑等）"),
        Column("style", "TEXT", "DEFAULT 'realistic'", "视听渲染与美术风格预设"),
        Column("tags", "TEXT", comment="商业标签与关键词列表"),
        Column("thumbnail", "TEXT", comment="封面缩略图地址"),
        Column("total_episodes", "INTEGER", "DEFAULT 1", "规划总集数（通常80-100集）"),
        Column("total_duration", "INTEGER", "DEFAULT 0", "全剧总时长估算（秒）"),
        Column("status", "TEXT", "DEFAULT 'draft'", "项目状态：draft/in_progress/completed/archived"),
        Column("metadata", "TEXT", comment="扩展元数据 JSON（含高概念、世界观、付费卡点配置等）"),
        Column("lock_status", "INTEGER", "DEFAULT 0", "剧本定稿锁定状态：0-编辑中可改，1-已锁定定稿只读"),
        Column("version_cursor", "INTEGER", "DEFAULT 1", "剧本全局协作与级联失效版本游标"),
        Column("created_at", "TEXT", comment="创建时间 ISO-8601"),
        Column("updated_at", "TEXT", comment="最后更新时间 ISO-8601"),
        Column("deleted_at", "TEXT", comment="软删除时间"),
    )),
    Table("episodes", (
        Column("id", "INTEGER", comment="分集记录唯一主键 ID"),
        Column("drama_id", "INTEGER", "NOT NULL DEFAULT 0", "关联短剧项目 ID"),
        Column("episode_number", "INTEGER", "DEFAULT 0", "分集序号（1-100）"),
        Column("title", "TEXT", "DEFAULT ''", "单集爆款标题"),
        Column("script_content", "TEXT", comment="分集视听正文 Markdown 完整文本"),
        Column("ast_blocks", "TEXT", comment="剧本正文 AST 结构化分块 JSON 快照（前3秒特写/动作场景/潜台词对白/片尾定格）"),
        Column("commercial_tag", "TEXT", comment="单集商业定位标签：free_hook/ad_clip/paywall_climax/regular"),
        Column("version", "INTEGER", "DEFAULT 1", "单集版本号，支持级联失效版本隔离"),
        Column("is_active", "INTEGER", "DEFAULT 1", "是否为当前有效版本：1-有效，0-已失效 Stale"),
        Column("patch_applied", "INTEGER", "DEFAULT 0", "是否已应用局部 AST 原位修补：1-已修补，0-未修补"),
        Column("description", "TEXT", comment="单集大纲与故事节拍描述"),
        Column("duration", "INTEGER", "DEFAULT 0", "单集时长秒数（60s/90s/120s）"),
        Column("video_url", "TEXT", comment="单集最终合成视频 MP4 地址"),
        Column("thumbnail", "TEXT", comment="单集视频封面图地址"),
        Column("status", "TEXT", "DEFAULT 'draft'", "分集状态：draft/writing/auditing/approved/rendering/done"),
        Column("created_at", "TEXT", comment="创建时间 ISO-8601"),
        Column("updated_at", "TEXT", comment="最后更新时间 ISO-8601"),
        Column("deleted_at", "TEXT", comment="软删除时间"),
    ), indexes=("drama_id",)),
    Table("storyboards", (
        Column("id", "INTEGER", comment="分镜唯一主键 ID"),
        Column("episode_id", "INTEGER", "NOT NULL DEFAULT 0", "关联分集 ID"),
        Column("scene_id", "INTEGER", comment="关联场景 ID"),
        Column("storyboard_number", "INTEGER", "DEFAULT 0", "分镜镜头序号"),
        Column("title", "TEXT", comment="分镜小标题"),
        Column("description", "TEXT", comment="分镜节拍描述"),
        Column("layout_description", "TEXT", comment="构图布局描述"),
        Column("location", "TEXT", comment="拍摄地点"),
        Column("time", "TEXT", comment="时间与光照"),
        Column("duration", "REAL", comment="镜头时长（秒）"),
        Column("dialogue", "TEXT", comment="台词与潜台词"),
        Column("narration", "TEXT", comment="旁白与内心独白"),
        Column("action", "TEXT", comment="影视动作指示"),
        Column("atmosphere", "TEXT", comment="现场氛围与情绪"),
        Column("image_prompt", "TEXT", comment="文生图 Prompt"),
        Column("video_prompt", "TEXT", comment="图生视频运镜 Prompt"),
        Column("characters", "TEXT", comment="出场角色名称列表"),
        Column("shot_type", "TEXT", comment="景别（特写/中景/全景等）"),
        Column("angle", "TEXT", comment="机位角度"),
        Column("movement", "TEXT", comment="镜头运动方式"),
        Column("image_url", "TEXT", comment="关键帧首帧图片 URL"),
        Column("local_path", "TEXT", comment="本地关键帧文件路径"),
        Column("main_panel_idx", "INTEGER", comment="主视区索引"),
        Column("video_url", "TEXT", comment="生成的单个镜头视频 URL"),
        Column("composed_image", "TEXT", comment="合成/拼版关键帧图"),
        Column("result", "TEXT", comment="生成产物综合元数据"),
        Column("emotion", "TEXT", comment="镜头主要情绪色彩"),
        Column("emotion_intensity", "INTEGER", comment="情绪强度（1-10）"),
        Column("error_msg", "TEXT", comment="渲染失败原因"),
        Column("segment_index", "INTEGER", "DEFAULT 0", "分段索引"),
        Column("segment_title", "TEXT", comment="分段标题"),
        Column("angle_h", "TEXT", comment="水平机位"),
        Column("angle_v", "TEXT", comment="垂直机位"),
        Column("angle_s", "TEXT", comment="特种机位"),
        Column("lighting_style", "TEXT", comment="光影风格"),
        Column("depth_of_field", "TEXT", comment="景深控制"),
        Column("polished_prompt", "TEXT", comment="精炼后的渲染提示词"),
        Column("continuity_snapshot", "TEXT", comment="镜头级连续性快照"),
        Column("audio_local_path", "TEXT", comment="对白音频本地路径"),
        Column("narration_audio_local_path", "TEXT", comment="旁白音频本地路径"),
        Column("creation_mode", "TEXT", "DEFAULT 'classic'", "创作模式"),
        Column("universal_segment_text", "TEXT", comment="全通用分段文本"),
        Column("first_frame_image_id", "INTEGER", comment="首帧图片资产 ID"),
        Column("last_frame_image_id", "INTEGER", comment="尾帧图片资产 ID"),
        Column("last_frame_image_url", "TEXT", comment="尾帧图片 URL"),
        Column("last_frame_local_path", "TEXT", comment="尾帧本地路径"),
        Column("task_fingerprint", "TEXT", comment="渲染任务唯一幂等指纹哈希，防网络重试重复扣费"),
        Column("status", "TEXT", "DEFAULT 'draft'", "分镜状态：draft/image_ready/video_ready/done/failed"),
        Column("created_at", "TEXT", comment="创建时间 ISO-8601"),
        Column("updated_at", "TEXT", comment="最后更新时间 ISO-8601"),
        Column("deleted_at", "TEXT", comment="软删除时间"),
    ), indexes=("episode_id", "scene_id")),
    Table("characters", (
        Column("id", "INTEGER", comment="角色唯一主键 ID"),
        Column("drama_id", "INTEGER", "NOT NULL DEFAULT 0", "关联短剧项目 ID"),
        Column("name", "TEXT", "NOT NULL DEFAULT ''", "角色姓名"),
        Column("role", "TEXT", comment="角色定位（如 protagonist/supporter/antagonist）"),
        Column("description", "TEXT", comment="角色背景与隐藏身份设定"),
        Column("personality", "TEXT", comment="性格特征与致命缺陷"),
        Column("appearance", "TEXT", comment="外貌特征与服装风格"),
        Column("image_url", "TEXT", comment="角色标准立绘或定妆图"),
        Column("local_path", "TEXT", comment="角色图片本地缓存路径"),
        Column("extra_images", "TEXT", comment="多角度/表情补充参考图 JSON 列表"),
        Column("voice_style", "TEXT", comment="音色风格画像与语气描述"),
        Column("sort_order", "INTEGER", "DEFAULT 0", "展示排序权重"),
        Column("error_msg", "TEXT", comment="资产生成错误信息"),
        Column("identity_anchors", "TEXT", comment="角色外貌一致性锚点特征词"),
        Column("style_tokens", "TEXT", comment="美术风格触发词"),
        Column("color_palette", "TEXT", comment="角色专属配色规范"),
        Column("four_view_image_url", "TEXT", comment="角色四视图拼接图地址"),
        Column("polished_prompt", "TEXT", comment="生图优化后的 Prompt"),
        Column("ref_image", "TEXT", comment="垫图参考图地址"),
        Column("stages", "TEXT", comment="角色多阶段外貌变化 JSON"),
        Column("seedance2_asset", "TEXT", comment="Seedance2 数字人资产绑定数据"),
        Column("seedance2_voice_asset", "TEXT", comment="Seedance2 语音克隆资产绑定数据"),
        Column("negative_prompt", "TEXT", comment="生图负向提示词"),
        Column("current_status", "TEXT", comment="运行时实时动态状态 JSON（伤势/财富/马甲暴露度）"),
        Column("growth_chain", "TEXT", comment="主角错误认知成长链 JSON 列表"),
        Column("created_at", "TEXT", comment="创建时间 ISO-8601"),
        Column("updated_at", "TEXT", comment="最后更新时间 ISO-8601"),
        Column("deleted_at", "TEXT", comment="软删除时间"),
    ), indexes=("drama_id",)),
    Table("episode_characters", (
        Column("episode_id", "INTEGER", "NOT NULL"),
        Column("character_id", "INTEGER", "NOT NULL"),
    ), primary_key="episode_id,character_id"),
    Table("scenes", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER", "NOT NULL DEFAULT 0"),
        Column("episode_id", "INTEGER"),
        Column("location", "TEXT"),
        Column("time", "TEXT"),
        Column("prompt", "TEXT"),
        Column("polished_prompt", "TEXT"),
        Column("image_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("extra_images", "TEXT"),
        Column("ref_image", "TEXT"),
        Column("negative_prompt", "TEXT"),
        Column("storyboard_count", "INTEGER", "DEFAULT 0"),
        Column("error_msg", "TEXT"),
        Column("status", "TEXT", "DEFAULT 'draft'"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
        Column("polished_prompt_single", "TEXT"),
    ), indexes=("drama_id", "episode_id")),
    Table("props", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER", "NOT NULL DEFAULT 0"),
        Column("episode_id", "INTEGER"),
        Column("name", "TEXT", "NOT NULL DEFAULT ''"),
        Column("type", "TEXT"),
        Column("description", "TEXT"),
        Column("prompt", "TEXT"),
        Column("image_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("extra_images", "TEXT"),
        Column("ref_image", "TEXT"),
        Column("negative_prompt", "TEXT"),
        Column("error_msg", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id", "episode_id")),
    Table("storyboard_props", (
        Column("storyboard_id", "INTEGER", "NOT NULL"),
        Column("prop_id", "INTEGER", "NOT NULL"),
    ), primary_key="storyboard_id,prop_id"),
    Table("frame_prompts", (
        Column("id", "INTEGER"),
        Column("storyboard_id", "INTEGER", "NOT NULL"),
        Column("frame_type", "TEXT"),
        Column("prompt", "TEXT"),
        Column("description", "TEXT"),
        Column("layout", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
    ), indexes=("storyboard_id",)),
    Table("ai_service_configs", (
        Column("id", "INTEGER"),
        Column("service_type", "TEXT", "NOT NULL DEFAULT 'text'"),
        Column("provider", "TEXT", "DEFAULT ''"),
        Column("name", "TEXT", "DEFAULT ''"),
        Column("base_url", "TEXT", "DEFAULT ''"),
        Column("api_key", "TEXT"),
        Column("model", "TEXT"),
        Column("default_model", "TEXT"),
        Column("endpoint", "TEXT"),
        Column("query_endpoint", "TEXT"),
        Column("priority", "INTEGER", "DEFAULT 0"),
        Column("is_default", "INTEGER", "DEFAULT 0"),
        Column("is_active", "INTEGER", "DEFAULT 1"),
        Column("settings", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
        Column("api_protocol", "TEXT", "NOT NULL DEFAULT ''"),
    )),
    Table("async_tasks", (
        Column("id", "TEXT"),
        Column("type", "TEXT", "NOT NULL DEFAULT ''"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("progress", "INTEGER", "DEFAULT 0"),
        Column("message", "TEXT"),
        Column("resource_id", "TEXT"),
        Column("completed_at", "TEXT"),
        Column("error", "TEXT"),
        Column("result", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), primary_key="id", indexes=("resource_id",)),
    Table("image_generations", (
        Column("id", "INTEGER"),
        Column("storyboard_id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("episode_id", "INTEGER"),
        Column("scene_id", "INTEGER"),
        Column("character_id", "INTEGER"),
        Column("provider", "TEXT"),
        Column("prompt", "TEXT"),
        Column("negative_prompt", "TEXT"),
        Column("model", "TEXT"),
        Column("frame_type", "TEXT"),
        Column("reference_images", "TEXT"),
        Column("use_first_frame_layout_lock", "INTEGER"),
        Column("size", "TEXT"),
        Column("quality", "TEXT"),
        Column("image_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("width", "INTEGER"),
        Column("height", "INTEGER"),
        Column("status", "TEXT"),
        Column("task_id", "TEXT"),
        Column("completed_at", "TEXT"),
        Column("error_msg", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("storyboard_id", "task_id")),
    Table("video_generations", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("storyboard_id", "INTEGER"),
        Column("provider", "TEXT"),
        Column("prompt", "TEXT"),
        Column("model", "TEXT"),
        Column("duration", "REAL"),
        Column("aspect_ratio", "TEXT"),
        Column("resolution", "TEXT"),
        Column("seed", "INTEGER"),
        Column("camera_fixed", "INTEGER"),
        Column("watermark", "INTEGER"),
        Column("image_url", "TEXT"),
        Column("first_frame_url", "TEXT"),
        Column("last_frame_url", "TEXT"),
        Column("reference_image_urls", "TEXT"),
        Column("video_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("status", "TEXT"),
        Column("task_id", "TEXT"),
        Column("provider_task_id", "TEXT"),
        Column("scene_id", "INTEGER"),
        Column("completed_at", "TEXT"),
        Column("error_msg", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("storyboard_id", "task_id")),
    Table("video_merges", (
        Column("id", "INTEGER"),
        Column("episode_id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("title", "TEXT"),
        Column("provider", "TEXT"),
        Column("model", "TEXT"),
        Column("status", "TEXT"),
        Column("scenes", "TEXT"),
        Column("merge_options", "TEXT"),
        Column("task_id", "TEXT"),
        Column("merged_url", "TEXT"),
        Column("duration", "INTEGER"),
        Column("completed_at", "TEXT"),
        Column("error_msg", "TEXT"),
        Column("created_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("episode_id", "task_id")),
    Table("assets", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("name", "TEXT"),
        Column("type", "TEXT"),
        Column("category", "TEXT"),
        Column("url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("file_size", "INTEGER"),
        Column("mime_type", "TEXT"),
        Column("width", "INTEGER"),
        Column("height", "INTEGER"),
        Column("duration", "REAL"),
        Column("image_gen_id", "INTEGER"),
        Column("video_gen_id", "INTEGER"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id",)),
    Table("character_libraries", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("name", "TEXT", "NOT NULL DEFAULT ''"),
        Column("category", "TEXT"),
        Column("image_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("description", "TEXT"),
        Column("appearance", "TEXT"),
        Column("tags", "TEXT"),
        Column("source_type", "TEXT"),
        Column("source_id", "TEXT"),
        Column("identity_anchors", "TEXT"),
        Column("style_tokens", "TEXT"),
        Column("color_palette", "TEXT"),
        Column("four_view_image_url", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id",)),
    Table("scene_libraries", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("location", "TEXT", "NOT NULL DEFAULT ''"),
        Column("time", "TEXT"),
        Column("prompt", "TEXT"),
        Column("description", "TEXT"),
        Column("image_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("category", "TEXT"),
        Column("tags", "TEXT"),
        Column("source_type", "TEXT"),
        Column("source_id", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id",)),
    Table("prop_libraries", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("name", "TEXT", "NOT NULL DEFAULT ''"),
        Column("description", "TEXT"),
        Column("prompt", "TEXT"),
        Column("image_url", "TEXT"),
        Column("local_path", "TEXT"),
        Column("category", "TEXT"),
        Column("tags", "TEXT"),
        Column("source_type", "TEXT"),
        Column("source_id", "TEXT"),
        Column("created_at", "TEXT"),
        Column("updated_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id",)),
    Table("prompt_overrides", (
        Column("id", "INTEGER"),
        Column("key", "TEXT", "NOT NULL"),
        Column("content", "TEXT", "NOT NULL"),
        Column("updated_at", "TEXT", "NOT NULL"),
    ), unique=("key",)),
    Table("image_proxy_cache", (
        Column("id", "INTEGER"),
        Column("cache_key", "TEXT", "NOT NULL DEFAULT ''"),
        Column("proxy_url", "TEXT", "NOT NULL DEFAULT ''"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
    ), unique=("cache_key",)),
    Table("ai_model_map", (
        Column("id", "INTEGER"),
        Column("key", "TEXT", "NOT NULL DEFAULT ''"),
        Column("service_type", "TEXT", "NOT NULL DEFAULT 'text'"),
        Column("config_id", "INTEGER"),
        Column("model_override", "TEXT"),
        Column("description", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
    ), unique=("key",)),
    Table("storyboard_characters", (
        Column("id", "INTEGER"),
        Column("storyboard_id", "INTEGER", "NOT NULL"),
        Column("character_id", "INTEGER", "NOT NULL"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
    ), indexes=("storyboard_id",)),
    Table("prompt_templates", (
        Column("id", "INTEGER"),
        Column("prompt_key", "TEXT", "NOT NULL"),
        Column("version", "INTEGER", "NOT NULL DEFAULT 1"),
        Column("name", "TEXT"),
        Column("agent_name", "TEXT"),
        Column("skill_key", "TEXT"),
        Column("locale", "TEXT", "NOT NULL DEFAULT 'zh'"),
        Column("model_family", "TEXT"),
        Column("template", "TEXT", "NOT NULL"),
        Column("input_schema", "TEXT"),
        Column("output_schema", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'draft'"),
        Column("tags", "TEXT"),
        Column("metadata", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("prompt_key", "skill_key", "agent_name", "status")),
    Table("prompt_runs", (
        Column("id", "INTEGER"),
        Column("prompt_key", "TEXT", "NOT NULL DEFAULT ''"),
        Column("prompt_version", "INTEGER", "DEFAULT 0"),
        Column("skill_key", "TEXT"),
        Column("agent_name", "TEXT"),
        Column("workflow_run_id", "TEXT"),
        Column("workflow_step_id", "TEXT"),
        Column("model", "TEXT"),
        Column("variables", "TEXT"),
        Column("context_snapshot", "TEXT"),
        Column("final_prompt", "TEXT"),
        Column("raw_output", "TEXT"),
        Column("parsed_output", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("error", "TEXT"),
        Column("latency_ms", "REAL"),
        Column("prompt_tokens", "INTEGER"),
        Column("completion_tokens", "INTEGER"),
        Column("cost", "REAL"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("prompt_key", "skill_key", "agent_name", "workflow_run_id", "status")),
    Table("skills", (
        Column("id", "INTEGER"),
        Column("skill_key", "TEXT", "NOT NULL"),
        Column("name", "TEXT", "NOT NULL DEFAULT ''"),
        Column("domain", "TEXT"),
        Column("locale", "TEXT", "NOT NULL DEFAULT 'zh'"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'draft'"),
        Column("current_version", "INTEGER", "NOT NULL DEFAULT 1"),
        Column("description", "TEXT"),
        Column("metadata", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("skill_key", "status")),
    Table("skill_versions", (
        Column("id", "INTEGER"),
        Column("skill_key", "TEXT", "NOT NULL"),
        Column("version", "INTEGER", "NOT NULL DEFAULT 1"),
        Column("input_schema", "TEXT"),
        Column("output_schema", "TEXT"),
        Column("prompt_keys", "TEXT"),
        Column("context_policy", "TEXT"),
        Column("model_policy", "TEXT"),
        Column("quality_checks", "TEXT"),
        Column("examples", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'draft'"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("skill_key", "status")),
    Table("context_snapshots", (
        Column("id", "INTEGER"),
        Column("scope_type", "TEXT", "NOT NULL DEFAULT 'global'"),
        Column("scope_id", "TEXT"),
        Column("workflow_run_id", "TEXT"),
        Column("skill_key", "TEXT"),
        Column("content", "TEXT", "NOT NULL"),
        Column("token_estimate", "INTEGER", "DEFAULT 0"),
        Column("source_refs", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
    ), indexes=("scope_type", "scope_id", "workflow_run_id", "skill_key")),
    Table("workflow_runs", (
        Column("id", "TEXT"),
        Column("type", "TEXT", "NOT NULL DEFAULT ''"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("drama_id", "INTEGER"),
        Column("episode_id", "INTEGER"),
        Column("user_request", "TEXT"),
        Column("input_payload", "TEXT"),
        Column("state", "TEXT"),
        Column("result", "TEXT"),
        Column("error", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("completed_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), primary_key="id", indexes=("type", "status", "drama_id", "episode_id")),
    Table("workflow_steps", (
        Column("id", "INTEGER"),
        Column("workflow_run_id", "TEXT", "NOT NULL"),
        Column("step_key", "TEXT", "NOT NULL DEFAULT ''"),
        Column("agent_name", "TEXT"),
        Column("skill_key", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("input_payload", "TEXT"),
        Column("output_payload", "TEXT"),
        Column("error", "TEXT"),
        Column("retry_count", "INTEGER", "NOT NULL DEFAULT 0"),
        Column("started_at", "TEXT"),
        Column("completed_at", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("workflow_run_id", "step_key", "agent_name", "skill_key", "status")),
    Table("queue_jobs", (
        Column("id", "TEXT"),
        Column("async_task_id", "TEXT"),
        Column("queue_name", "TEXT", "NOT NULL DEFAULT 'default'"),
        Column("task_type", "TEXT", "NOT NULL DEFAULT ''"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("priority", "INTEGER", "NOT NULL DEFAULT 0"),
        Column("payload", "TEXT"),
        Column("result", "TEXT"),
        Column("error", "TEXT"),
        Column("attempts", "INTEGER", "NOT NULL DEFAULT 0"),
        Column("max_attempts", "INTEGER", "NOT NULL DEFAULT 3"),
        Column("locked_by", "TEXT"),
        Column("locked_at", "TEXT"),
        Column("run_after", "TEXT"),
        Column("dispatched_at", "TEXT", "", "最近一次投递到 Redis Broker 的时间"),
        Column("broker_message_id", "TEXT", "", "Dramatiq 消息 ID，用于链路追踪和去重诊断"),
        Column("workflow_run_id", "TEXT"),
        Column("workflow_step_id", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("completed_at", "TEXT"),
        Column("deleted_at", "TEXT"),
    ), primary_key="id", indexes=("queue_name", "task_type", "status", "dispatched_at", "workflow_run_id", "workflow_step_id")),
    Table("worker_nodes", (
        Column("id", "TEXT"),
        Column("worker_id", "TEXT", "NOT NULL"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'online'"),
        Column("queues", "TEXT"),
        Column("hostname", "TEXT"),
        Column("process_id", "INTEGER"),
        Column("heartbeat_at", "TEXT"),
        Column("started_at", "TEXT"),
        Column("stopped_at", "TEXT"),
        Column("metadata", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), primary_key="id", indexes=("worker_id", "status", "heartbeat_at")),
    Table("agent_runs", (
        Column("id", "INTEGER"),
        Column("workflow_run_id", "TEXT"),
        Column("workflow_step_id", "TEXT"),
        Column("agent_name", "TEXT", "NOT NULL DEFAULT ''"),
        Column("skill_key", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("input_payload", "TEXT"),
        Column("output_payload", "TEXT"),
        Column("memory_refs", "TEXT"),
        Column("prompt_run_id", "TEXT"),
        Column("error", "TEXT"),
        Column("latency_ms", "REAL"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("workflow_run_id", "workflow_step_id", "agent_name", "skill_key", "status")),
    Table("memory_items", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("episode_id", "INTEGER"),
        Column("memory_type", "TEXT", "NOT NULL DEFAULT 'note'"),
        Column("scope", "TEXT", "NOT NULL DEFAULT 'drama'"),
        Column("title", "TEXT"),
        Column("content", "TEXT", "NOT NULL"),
        Column("summary", "TEXT"),
        Column("keywords", "TEXT"),
        Column("embedding_ref", "TEXT"),
        Column("source_type", "TEXT"),
        Column("source_id", "TEXT"),
        Column("metadata", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'active'", "记忆状态：active/conflict/expired/disabled"),
        Column("expires_at", "TEXT", "", "记忆过期时间，空值表示长期有效"),
        Column("conflict_group_id", "TEXT", "", "冲突组标识，同组记忆需要人工裁决"),
        Column("confidence", "REAL", "DEFAULT 1.0", "记忆可信度，取值范围 0 到 1"),
        Column("revision", "INTEGER", "NOT NULL DEFAULT 1", "人工或自动修订版本号"),
        Column("manually_edited_at", "TEXT", "", "最近一次人工修订时间"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id", "episode_id", "memory_type", "scope", "status", "expires_at", "conflict_group_id")),
    Table("character_voice_profiles", (
        Column("id", "INTEGER"),
        Column("character_id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("character_name", "TEXT", "NOT NULL DEFAULT ''"),
        Column("voice_prompt", "TEXT"),
        Column("timbre", "TEXT"),
        Column("speed_ratio", "REAL", "DEFAULT 1.0"),
        Column("pitch_ratio", "REAL", "DEFAULT 1.0"),
        Column("emotion_rules", "TEXT"),
        Column("provider", "TEXT"),
        Column("voice_id", "TEXT"),
        Column("reference_audio_url", "TEXT"),
        Column("negative_traits", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'draft'"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("character_id", "drama_id", "status")),
    Table("music_bibles", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER", "NOT NULL"),
        Column("overall_style", "TEXT"),
        Column("theme_prompt", "TEXT"),
        Column("instruments", "TEXT"),
        Column("bpm_range", "TEXT"),
        Column("emotional_palette", "TEXT"),
        Column("mixing_rules", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'draft'"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id", "status")),
    Table("music_cues", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("episode_id", "INTEGER"),
        Column("storyboard_id", "INTEGER"),
        Column("cue_type", "TEXT", "NOT NULL DEFAULT 'bgm'"),
        Column("emotion", "TEXT"),
        Column("bgm_prompt", "TEXT"),
        Column("sfx_prompt", "TEXT"),
        Column("volume", "REAL", "DEFAULT 0.7"),
        Column("start_offset", "REAL", "DEFAULT 0"),
        Column("fade_in", "REAL", "DEFAULT 0.5"),
        Column("fade_out", "REAL", "DEFAULT 1.0"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'draft'"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id", "episode_id", "storyboard_id", "status")),
    Table("audio_generations", (
        Column("id", "INTEGER"),
        Column("drama_id", "INTEGER"),
        Column("episode_id", "INTEGER"),
        Column("storyboard_id", "INTEGER"),
        Column("character_id", "INTEGER"),
        Column("generation_type", "TEXT", "NOT NULL DEFAULT 'tts'"),
        Column("provider", "TEXT"),
        Column("prompt", "TEXT"),
        Column("result", "TEXT"),
        Column("local_path", "TEXT"),
        Column("url", "TEXT"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'pending'"),
        Column("error", "TEXT"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
        Column("deleted_at", "TEXT"),
    ), indexes=("drama_id", "episode_id", "storyboard_id", "character_id", "generation_type", "status")),
    Table("quality_reports", (
        Column("id", "INTEGER", comment="质检报告唯一主键 ID"),
        Column("workflow_run_id", "TEXT", comment="关联工作流运行 ID"),
        Column("workflow_step_id", "TEXT", comment="关联步骤 ID"),
        Column("drama_id", "INTEGER", comment="关联短剧 ID"),
        Column("episode_id", "INTEGER", comment="关联分集 ID"),
        Column("report_type", "TEXT", "NOT NULL DEFAULT 'creative_review'", "报告类型（creative_review/five_stage_qa）"),
        Column("status", "TEXT", "NOT NULL DEFAULT 'open'", "报告状态：open/resolved/rejected"),
        Column("score", "REAL", comment="质检综合总得分（0-100）"),
        Column("passed", "INTEGER", "DEFAULT 0", "五阶质检是否放行：1-放行(>=85分)，0-不合格"),
        Column("patch_applied", "INTEGER", "DEFAULT 0", "是否经过 AST 局部原位修补自愈：1-已修补，0-初审"),
        Column("radar_scores", "TEXT", comment="五阶质检分项雷达分 JSON: structure, character, scene, language, continuity"),
        Column("issues", "TEXT", comment="发现的核心缺陷与扣分点 JSON 列表"),
        Column("suggestions", "TEXT", comment="结构化定向修改建议"),
        Column("raw_report", "TEXT", comment="原始质检输出文本"),
        Column("created_at", "TEXT", "NOT NULL DEFAULT ''", "创建时间 ISO-8601"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''", "最后更新时间 ISO-8601"),
        Column("deleted_at", "TEXT", comment="软删除时间"),
    ), indexes=("workflow_run_id", "drama_id", "episode_id", "report_type", "status")),
    Table("global_settings", (
        Column("key", "TEXT", "NOT NULL"),
        Column("value", "TEXT", "NOT NULL DEFAULT ''"),
        Column("updated_at", "TEXT", "NOT NULL DEFAULT ''"),
    ), primary_key="key"),
]

# 被索引的 TEXT 列自动转 VARCHAR（MySQL 8 不允许 TEXT 作索引列）
for _t in TABLES:
    for _col in _t.indexes:
        _c = next((x for x in _t.columns if x.name == _col), None)
        if _c is not None and _c.type == "TEXT":
            VARCHAR_OVERRIDES.setdefault(_col, 64)

CREATE_SQL: list[str] = [build_create_sql(t) for t in TABLES]

# 附加索引（建表后执行；唯一索引）
UNIQUE_INDEX_SQL: list[str] = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_overrides_key ON prompt_overrides(`key`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_image_proxy_cache_key ON image_proxy_cache(`cache_key`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_model_map_key ON ai_model_map(`key`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_templates_key_version ON prompt_templates(`prompt_key`, `version`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_skills_key ON skills(`skill_key`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_skill_versions_key_version ON skill_versions(`skill_key`, `version`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_music_bibles_drama_id ON music_bibles(`drama_id`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_worker_nodes_worker_id ON worker_nodes(`worker_id`)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_global_settings_key ON global_settings(`key`)",
]

# 普通索引
INDEX_SQL: list[str] = []
for t in TABLES:
    for col in t.indexes:
        INDEX_SQL.append(f"CREATE INDEX IF NOT EXISTS ix_{t.name}_{col} ON {t.name}(`{col}`)")


def ensure_schema(conn) -> None:
    """幂等建表（统一支持 MySQL 与 SQLite）。

    MySQL 8 不支持 CREATE INDEX IF NOT EXISTS，改为先查 information_schema
    判断索引是否已存在，避免重复创建报错；SQLite 则自动转换 AUTO_INCREMENT 及方言子句。
    """
    is_sqlite = getattr(conn.dialect, "name", "") == "sqlite"
    for sql in CREATE_SQL:
        if is_sqlite:
            sql_sqlite = re.sub(r"\)\s*ENGINE=InnoDB.*$", ")", sql, flags=re.MULTILINE)
            sql_sqlite = re.sub(r"BIGINT\s+NOT\s+NULL\s+AUTO_INCREMENT\s+PRIMARY\s+KEY", "INTEGER PRIMARY KEY AUTOINCREMENT", sql_sqlite)
            sql_sqlite = re.sub(r"MEDIUMTEXT", "TEXT", sql_sqlite)
            sql_sqlite = re.sub(r"\s+COMMENT\s+'(?:''|[^'])*'", "", sql_sqlite)
            conn.execute(text(sql_sqlite))
        else:
            conn.execute(text(sql))

    # 已有数据库也要幂等补列，不能只依赖 CREATE TABLE IF NOT EXISTS。
    from sqlalchemy import inspect

    inspector = inspect(conn)
    for table in TABLES:
        existing = {item["name"] for item in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            if is_sqlite:
                sql_type = "INTEGER" if column.type == "INTEGER" else "REAL" if column.type == "REAL" else "TEXT"
                extra = column.extra
            else:
                sql_type = _sqltype(column)
                extra = _strip_text_default(column.extra) if sql_type in {"TEXT", "MEDIUMTEXT"} else column.extra
            comment_sql = ""
            if not is_sqlite and column.comment:
                escaped_comment = column.comment.replace("'", "''")
                comment_sql = f" COMMENT '{escaped_comment}'"
            conn.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN `{column.name}` {sql_type} {extra}{comment_sql}".rstrip()))

    for sql in UNIQUE_INDEX_SQL + INDEX_SQL:
        if is_sqlite:
            conn.execute(text(sql))
            continue
        m = re.match(r"CREATE (?:UNIQUE )?INDEX (?:IF NOT EXISTS )?(\S+) ON\s+`?(\w+)`?\(", sql)
        if not m:
            continue
        idx_name, table = m.group(1), m.group(2)
        exists = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
            ),
            {"t": table, "i": idx_name},
        ).scalar()
        if not exists:
            # MySQL 不支持 IF NOT EXISTS 子句，剔除后执行
            conn.execute(text(re.sub(r"\s+IF NOT EXISTS\s+", " ", sql, count=1)))



def all_ddl() -> list[str]:
    return CREATE_SQL + UNIQUE_INDEX_SQL + INDEX_SQL
