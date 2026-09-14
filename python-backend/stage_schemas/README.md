# 短剧工业化创作五阶段 JSON 契约目录 (Stage Schemas)

本目录独立存放《短剧剧本·全流程工业化创作》五大核心阶段的标准 JSON Schema 与输入/输出契约定义。每个文件定义了该阶段大模型的结构化输出标准、验证规则以及与后端 Python 数据库持久化方法的映射。

---

## 阶段契约文件索引

| 阶段 | 文件名 | 核心职责 | 对应 Python 落库函数 |
| :--- | :--- | :--- | :--- |
| **阶段 1** | [stage1_concept_design.json](stage1_concept_design.json) | 立项与高概念、3秒强视觉钩子、因果四幕、受众与付费卡点规划 | `_persist_stage1_to_db` |
| **阶段 2** | [stage2_story_bible.json](stage2_story_bible.json) | 故事圣经、3-5个主场景、人物小传与错误认知链、关系网与伏笔库 | `_persist_stage2_to_db` |
| **阶段 3** | [stage3_episode_outlines.json](stage3_episode_outlines.json) | 全剧分集大纲骨架、商业标签、结尾断章与 **HITL 状态机挂起/干预** | `_persist_stage3_to_db` |
| **阶段 4** | [stage4_batch_script_ast.json](stage4_batch_script_ast.json) | 批次受控并发正文撰写、AST 结构化分块、五阶质检与局部手术修补 | `_persist_stage4_worker_result_to_db` |
| **阶段 5** | [stage5_visual_bridge.json](stage5_visual_bridge.json) | 全剧定稿锁定、版本游标冻结、Script-to-Visual Bridge 分镜与音效 | `_persist_stage5_to_db` |

---

## 核心设计规范

1. **与 LangGraph 瘦状态机 (Lean State) 保持一致**：
   - 内存状态机仅保存当前活跃批次（2~3集）的滑动窗口数据；
   - 历史全剧正文与分镜由数据库 (`dramas`, `episodes`, `characters`, `scenes`, `storyboards`) 外挂持久化。
2. **HITL 人工干预模式**：
   - 阶段三生成后自动触发 `interrupt_after=["outline_generation"]` 挂起；
   - 人工通过 [stage3_episode_outlines.json](stage3_episode_outlines.json) 中的 `hitl_intervention_payload` 格式覆写状态并唤醒恢复。
3. **AST 级局部修补**：
   - 阶段四对质检不达标的集数，通过 [stage4_batch_script_ast.json](stage4_batch_script_ast.json) 的 `patch_request_payload` 定向修补特定分块（`hook_3s`, `action_blocks`, `dialogue_blocks`, `ending_hook`）。
