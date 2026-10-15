---
name: stage7_storyboard_audio_subtitle_plan
overview: 落地阶段 7（视听分镜、AI母音音频驱动、首尾帧多图模式与毫秒级字幕）的六表联动原子持久化与全链路闭环实现。
todos:
  - id: update-schema-ddl
    content: 在 schema.py 中更新表定义：新增 storyboard_subtitles，扩充 storyboards 与 storyboard_audios 字段及 comment 注释
    status: completed
  - id: enhance-stage6-asset-lookup
    content: 在 drama_storage_adapter.py 中增强 _load_stage6_asset_lookup_maps，加载母音档案与道具战损映射字典
    status: completed
    dependencies:
      - update-schema-ddl
  - id: refactor-stage7-node-data-contract
    content: 在 stage7_storyboard_srt.py 中规范首尾帧、多图槽位、纯净发音台本与口型动力学参数的结构化导出
    status: completed
    dependencies:
      - update-schema-ddl
  - id: implement-six-table-persistence
    content: 在 drama_storage_adapter.py 中实现六表级联清理与原子落库函数，彻底打通分镜、母音音频与字幕存储
    status: completed
    dependencies:
      - enhance-stage6-asset-lookup
      - refactor-stage7-node-data-contract
  - id: verify-and-lsp-check
    content: 使用 [skill:lsp-code-analysis] 验证阶段 7 节点与存储适配器的符号引用与接口契约一致性
    status: completed
    dependencies:
      - implement-six-table-persistence
---

## 需求概述与业务边界
在“两程九阶”工业级短剧生成流水线中，针对**阶段 7（Stage 7 分镜设计与毫秒级 SRT）**的产物未正常持久化、视听资产与阶段 6 资产真理源脱节的问题，在**严格保持流水线现有流程与拓扑结构不变**的前提下，实施具体的系统编码改造。

## 核心功能与技术产出
1. **数据库元数据完善与新建表（DDL 带字段与表级注释）**：
   - 完善现存表 `storyboards`，补齐时间轴区间、双模式选型（首尾帧/多图参考）、目标引擎等字段；
   - 补齐现存表 `storyboard_audios`，支持剥离括号动作后的纯净发音台本（clean_dialogue_text）、情感控制词（tts_prompt）、口型动力学配置（lipsync_dynamics）、语速与音高微调；
   - 新增分镜行级字幕明细表 `storyboard_subtitles`，承载整集全局毫秒时码、说话人、纯净台词与拟音描述；
   - 激活现存表 `frame_prompts`，承载模式 A 首尾静态关键帧（first/last）与三段式运动轨迹插值描述。
2. **全流程资产血统闭环与映射解析**：
   - 对白/旁白通过角色名称严格对齐阶段 6 角色主表 `characters.id` 与角色专属母音档案 `character_voice_profiles.id`，提取底层引擎预设音色 `voice_id`，并计算防重复合成的 SHA-256 幂等指纹；
   - 道具严格对齐阶段 6 的二级战损状态表 `prop_damage_states.id`（区分完好 S0 与破损 S1）；
   - 执行权威多资源槽位编排铁律：图 1 绑定场景、图 2..k 绑定角色、图 k+1..4 绑定道具，提示词引用符号（图 1~4、音频 1~3）与数组槽位 100% 强一致。
3. **适配器六表原子持久化与级联清理**：
   - 升级 `drama_storage_adapter.py`，实现 `storyboards`、`frame_prompts`、`storyboard_characters`、`storyboard_props`、`storyboard_audios`、`storyboard_subtitles` 六表在单个事务内的级联清理与原子写入；
   - 全面修复 Pydantic 模型属性访问与 Dict 键值访问的兼容性问题，杜绝分镜数据在落库时静默丢失。


## 技术选型
- **后端框架与语言**：Python 3.11+ / FastAPI / SQLAlchemy (Session & Text SQL) / SQLite & PostgreSQL
- **状态管理与契约**：Pydantic V2 (`BaseModel`, `ConfigDict(extra="allow")`, `model_validate`)
- **数据流转架构**：LangGraph / TwoJourneyRunner (`EpisodeScopedSubState` 单集轻量瞬时子状态)

## 技术方案与实现策略
1. **Schema 元数据层 (`app/db/schema.py`)**：
   - 保持现有 `Table` 与 `Column` 声明式元数据风格；
   - 登记新增的 `storyboard_subtitles` 表；
   - 在 `storyboards` 与 `storyboard_audios` 中扩充缺失字段，所有新增及修正字段一律赋予详细的工业级 `comment` 说明。
2. **阶段 6 资产字典增强 (`app/workflows/adapters/drama_storage_adapter.py`)**：
   - 在 `_load_stage6_asset_lookup_maps` 中补充从 `character_voice_profiles` 加载全剧角色母音档案，建立 `voice_by_char_id` 与 `voice_by_char_name` 映射；
   - 强化 `prop_damage_states` 二级战损与三级切片的反向解析，确保道具槽位能准确回填 `damage_state_id`。
3. **分镜节点提纯与口型声学解耦 (`app/workflows/nodes/stage7_storyboard_srt.py`)**：
   - 提取分镜台词时，执行纯净台本剥离算法（去除括号动作指示），生成 `clean_dialogue_text`；
   - 严格隔离视频 Prompt 与口型底层生理参数，将 `lipsync_dynamics` 保留在音频/字幕实体中。
4. **六表联动持久化函数设计 (`_persist_episode_storyboards_6tables`)**：
   - 封装 `_s_val(obj, key, default=None)` 辅助方法，统一兼容 Pydantic 实例属性访问与字典检索；
   - 前置倒序级联清理：按 `storyboard_subtitles` -> `storyboard_audios` -> `frame_prompts` -> `storyboard_characters` -> `storyboard_props` -> `storyboards` 幂等清理旧数据；
   - 单事务批量写入：循环 `validated_shots`，依次插入主表与 5 张从表，最后回填更新 `episodes.ast_blocks` 中的 `srt_export` 与 `mode_b_manifest_check`。

## 目录结构变更清单

```
python-backend/
├── app/
│   ├── db/
│   │   └── schema.py                    # [MODIFY] 登记 storyboard_subtitles 表结构定义，扩充 storyboards 与 storyboard_audios 字段，补全字段 comment 与索引。
│   └── workflows/
│       ├── nodes/
│       │   └── stage7_storyboard_srt.py # [MODIFY] 优化纯净发音台本清洗、首尾帧与多图提示词结构化解构、母音资产与口型参数标准化封装。
│       └── adapters/
│           └── drama_storage_adapter.py # [MODIFY] 扩展 _load_stage6_asset_lookup_maps 母音与道具战损加载；将 3 表持久化重构成 6 表原子级联持久化。
```

## 关键代码接口结构与 DDL 定义

### 1. 新增表 `storyboard_subtitles` Schema 定义
```python
Table("storyboard_subtitles", (
    Column("id", "INTEGER", comment="字幕条目唯一自增主键ID"),
    Column("drama_id", "INTEGER", "NOT NULL DEFAULT 0", comment="所属短剧项目ID，关联 dramas.id"),
    Column("episode_id", "INTEGER", "NOT NULL DEFAULT 0", comment="所属分集ID，关联 episodes.id"),
    Column("storyboard_id", "INTEGER", "NOT NULL", comment="所属分镜镜头ID，严格关联 storyboards.id（级联删除）"),
    Column("sequence_order", "INT", "NOT NULL DEFAULT 1", comment="整集内全局字幕自然排序号（从1递增，严格对应.srt文件序号）"),
    Column("subtitle_type", "TEXT", "NOT NULL DEFAULT 'dialogue'", comment="字幕条目类型：dialogue(角色对白)/narration(旁白)/inner_voice(心声OS)/foley_cue(拟音字幕描述)"),
    Column("character_id", "INTEGER", comment="发音角色ID，关联 characters.id（纯旁白或拟音字幕为NULL）"),
    Column("speaker_name", "TEXT", "NOT NULL DEFAULT ''", comment="说话人名称（用于字幕前缀或字幕轴元数据，如 陆沉、神秘人）"),
    Column("text_content", "TEXT", "NOT NULL DEFAULT ''", comment="字幕屏幕展示正文（纯净台词或拟音标记，如\"你以为能逃出这里？\"）"),
    Column("start_ms", "INTEGER", "NOT NULL DEFAULT 0", comment="整集全局绝对发声起始时间戳（毫秒）"),
    Column("end_ms", "INTEGER", "NOT NULL DEFAULT 0", comment="整集全局绝对发声结束时间戳（毫秒）"),
    Column("duration_ms", "INTEGER", "NOT NULL DEFAULT 0", comment="字幕展示持续时间（毫秒）"),
    Column("srt_timecode", "TEXT", "NOT NULL DEFAULT ''", comment="广播级标准SRT时码格式，如 00:00:23,500 --> 00:00:26,200"),
    Column("audio_id", "INTEGER", comment="关联对应的分镜音频记录ID，关联 storyboard_audios.id"),
    Column("style_config", "TEXT", comment="字幕动效与样式JSON（高潮变色、重音加重、字级弹出特效）"),
    Column("created_at", "TEXT", "NOT NULL DEFAULT ''", comment="记录创建时间 ISO-8601"),
    Column("updated_at", "TEXT", "NOT NULL DEFAULT ''", comment="记录最后更新时间 ISO-8601"),
), indexes=("episode_id", "storyboard_id", "sequence_order"), comment="分镜毫秒级广播级字幕明细表：承载行级SRT字幕条目，实现镜头画面、说话人角色、干声音频与广播级时码的毫秒对齐")
```


## Agent Extensions
### Skill
- **lsp-code-analysis**
  - Purpose: 对修改后的数据表模型、字段引用与适配器调用进行代码语义与引用符号分析
  - Expected outcome: 确保修改后的数据字段和调用链在全项目中无拼写错误或接口调用不匹配
