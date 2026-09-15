# 剧本创作工坊 AI 原创短剧工业化 SOP (SKILL.md) 全流程 LangGraph 改造方案

---

## 1. 方案背景与目标

当前 `LocalMiniDrama` 的剧本创作工坊实现了初步的“五阶段状态机”（创意立项 ➔ 故事圣经 ➔ 三级大纲 ➔ 正文撰写 ➔ 复盘定稿），但与最新标准工业化 SOP（`SKILL.md`：**AI Serial Micro-Drama Master SOP 终极工业全息闭环版**）相比，仍存在本质上的工程与剧作割裂：
1. **阶段流转断层**：原管线止步于文学正文生成，下游视听资产（角色、道具、场景）仅通过 Bridge 做离线名词提取，分镜与音频工程缺乏自动化编排；
2. **缺乏对抗性质检**：原质检为单向静态评分，缺乏“蓝军客观合规 + 红军魔鬼挑刺（区分 Blocking 阻断与 Warning 警示）”的红蓝对抗机制；
3. **缺少长短期记忆便签流转**：缺少阶段 1 禁令与核心讽刺向阶段 2~5 的硬性继承，缺少上一集物理状态向下一集开场的 0 秒咬合；
4. **视听分镜缺乏工业决策树**：未落地“模式 A 首尾帧（防物体形变崩坏） vs 模式 B 多图参考（保对白微表情）”以及口型动力学、Audio Ducking 侧链避让等广播级规范。

**改造总目标**：
以 LangGraph 状态机为核心底座，将剧本创作工坊全面升级为 **“两程九阶（Two-Journey, Nine-Stage）”** 工业化生产管线，实现“文学全季锁死定稿 ➔ 单集视听/分镜/混音微循环滚动”的全息自动化生产闭环。

---

## 2. @SKILL.md 核心工业体系深度拆解

### 2.1 双程工业架构 (Two-Journey Architecture)

```
====================================================================================================
【第一程：文学故事工程 (The Literary Journey)】—— 编剧室闭环，全季故事逻辑与伏笔锁死
====================================================================================================
[阶段 1: 题材破壁与创意引擎] ──► 01_bible.json (候选片名矩阵 / 双轨禁令母集 / 核心讽刺 / 终局核爆点)
          │
          ▼
[阶段 2: 角色人设与心理建模] ──► 02_characters.json (心理四元组 / 语言与行为指纹 / 随身旧物锚定)
          │
          ▼
[阶段 3: 空间设计与物证规划] ──► 03_environments_props.json (场景三层做旧架构 / 反转道具与+3dB拟音)
          │
          ▼
[阶段 4: 全季爆款分集大纲规划] ─► 04_outline.json + 04_audio_bible.json (3大音乐主题动机 / 工笔级任务卡)
          │
          ▼
[阶段 5: 疾速波次连续吞吐] ──► episodes_screenplay/ep_01.json ~ ep_NN.json (3~4集Mini-Arc波次JSON)
          │
          ▼
   🛑【第一程全季文学定稿门控 (The Literary Gatekeeper)】（全季剧本锁死，严禁未定稿抢跑做视听）

====================================================================================================
【第二程：视听资产与分镜工程 (The Visual & Storyboard Journey)】—— 单集微循环流水线 (Episode Loop)
====================================================================================================
 ┌──►【单集微循环：第 XX 集启动】(读取当前集文学稿 ep_XX.json 与上一集物理快照)
 │        │
 │        ▼
 │   [阶段 6: 分集增量视听资产准备] ──► 查库 05_visual_audio_assets.json 复用，按需生成，输出本集资源引单
 │        │ 🛑【阶段 6 资产审查门控】
 │        ▼
 │   [阶段 7: 单镜头工业执行表] ──► 首尾帧 vs 多图双模式选型 + 口型动力学 + 声学指令 + 导出 SRT
 │        │ 🛑【阶段 7 分镜审查门控】
 │        ▼
 │   [阶段 8: 多轨智能音频工程] ──► 定制BGM Prompt + 动态Ducking避让 + 断崖静音 + NLE剪辑指南
 │        │ 🛑【阶段 8 单集结项审查门控】
 │        │
 └────────┴──► 若 XX < 全季总集数：提取【集尾物理快照】，自动步入【第 XX+1 集阶段 6】
               若 XX == 全季总集数：全流程收官，交付全套工业资产！
```

### 2.2 阶段间长短期记忆输入/输出契约矩阵 (Memory I/O Matrix)

| 阶段 | 读取的【全局长期记忆】 | 读取的【流动短期记忆】 | 产出的【本阶段长期资产】 | 产出的【下传短期记忆便签】 |
| :--- | :--- | :--- | :--- | :--- |
| **阶段 1：题材破壁** | 用户初始输入 | 无（管线启动） | `01_bible.json`<br>- 4大维度片名矩阵<br>- 10大俗套+3大廉价禁令<br>- Logline/核心讽刺/终局核爆点 | **【短期记忆 A：人设禁令子集 + 核心讽刺】**<br>提炼主角致命缺陷及防伟光正/防龙傲天指令。 |
| **阶段 2：角色人设建模** | `01_bible.json` | **【短期记忆 A】** | `02_characters.json`<br>- 心理四元组 (Want/Need/Lie/Ghost)<br>- 语言指纹与行为习惯<br>- 随身核心锚定物 | **【短期记忆 B：角色随身旧物与活动轨迹】**<br>汇总角色生活阶层空间与随身物品。 |
| **阶段 3：空间与物证规划** | `01_bible.json`<br>`02_characters.json` | **【短期记忆 B】** | `03_environments_props.json`<br>- 核心场景三层做旧规划<br>- 核心物证叙事隐喻、破损尺度与物理阻力 | **【短期记忆 C：大纲冲突要素包】**<br>提炼推动剧情大反转的核心场景与反转道具。 |
| **阶段 4：全季分集大纲** | `01`核爆点/双轨禁令<br>`02`人物欲望<br>`03`核心物证 | **【短期记忆 C】** | `04_outline.json` & `04_audio_bible.json`<br>- 3套贯穿全剧的具象音乐主题动机母库<br>- 各集前3s Hook/45s微反转/潜台词/断点 | **【短期记忆 D：全季分集剧作路线图】**<br>各集核心戏剧任务与因果悬念链条。 |
| **阶段 5：全季文学剧本波次产出** | `01`双轨禁令母集<br>`02`角色语言指纹<br>`03`场景做旧隐喻<br>`04`工笔级任务卡 | **【单元内物理接力短期记忆】**<br>(上一集集尾物理快照) | `episodes_screenplay/ep_01.json ~ ep_NN.json`<br>- 3-4集/波次结构化纯文学 JSON 数组<br>- 事前三道安全护栏锁 (潜台词/禁词/代价毛刺) | **【第一程终结：全季文学故事闭环快照】**<br>全季文学正式定稿锁死。 |
| **阶段 6：分集增量视听资产准备** | 阶段 1-5 全量定稿文学 + `05_visual_audio_assets.json` (真理源) | **【当前集文学剧本 JSON】** | `05_visual_audio_assets.json`<br>- 角色三级、场景两级、道具三级归类注册<br>- 已有合格资产 100% 继承复用，缺失项按需生成<br>- 状态分支单项图 | **【本集视听资源引单 (Manifest)】**<br>按角色、场景、道具、声音分类引单。 |
| **阶段 7：单镜头工业执行表** | `01`画幅/时长<br>`05`已批准视听资产总库<br>`ep_XX.json` | 1. **当前集文学稿**<br>2. **上一集分镜最后一秒物理快照** | `storyboards/sb_XX.json`<br>- 首尾帧 vs 多图精准选型<br>- 全息声画绑定与口型动力学参数<br>- **内置毫秒级 SRT 字幕资产** | **【本集视听执行包】**<br>机器可读执行契约 + 集尾物理快照。 |
| **阶段 8：多轨智能音频混音工程** | `01`风格时长<br>`04_audio_bible.json`<br>阶段 7 分镜头执行表 | 阶段 7 绝对毫秒时间轴与 SRT 掩码 | `audio_mastering/ep_XX_master.json`<br>- 动态分段 BGM Prompt<br>- 对白侧链避让 (-18~-22dB)<br>- 断崖式主观静音 (-inf dB)<br>- NLE 剪辑轨道指南 | **【单集最终视听交付物】**<br>推进下一集或全剧圆满结项。 |

---

## 3. 现有代码实现分析与差距识别 (Gap Analysis)

| 核心组件 | 现有实现状态 | `SKILL.md` 标准要求 | 差距与改造对策 |
| :--- | :--- | :--- | :--- |
| **LangGraph 状态机拓扑** | 单层 5 节点线性图（`intake` ➔ `bible` ➔ `outline` ➔ `single_episode` ➔ `finalize`） | **双程拓扑**：第一程文学 5 阶闭环 + 第二程单集微循环子图 (6 ➔ 7 ➔ 8 循环) | 重构主图为两程架构，引入单集微循环子图与集数推进条件路由 |
| **自审与质检机制** | 静态规则质检，单集打分（`QAReport`，>=85分放行） | **红蓝对抗 AI 质量自审**：蓝军客观审查 + 红军魔鬼挑刺，区分 🔴 Blocking 与 🟡 Warning | 新增 `RedBlueAuditReport` 模型与自审 Agent 节点，Blocking 触发就地重构，Warning 呈报前端 HITL |
| **正文撰写并发模型** | 单集孤立并发分发 (`Send API`) | **3~4 集戏剧小高潮单元 (Mini-Arc) 连续吞吐**，事前护栏，集间 0 秒物理咬合 | 改造批次调度为 Mini-Arc 单元吞吐，在 JSON 结构中嵌入 `subtext_matrix` 与 `previous_episode_physical_pickup` |
| **第一程定稿门控** | 阶段 5 结束后由 `script_to_visual_bridge.py` 离线提取实体 | **严格文学定稿门禁**：全季文学必须全量定稿加锁，方可解锁第二程 | 引入 `LiteraryGatekeeper` 节点，前置锁定剧本，杜绝抢跑视听造成算力报废 |
| **视听资产管理** | 前端手动上传/生成，无统一版本注册表 | **全局唯一真理源 `05_visual_audio_assets.json`**，严格复用已批准资产，按需增量生成 | 构建资产总库注册机制与分级扫描器，输出单集资源引单 |
| **分镜生成模型** | 简单提示词切分，无生成选型指导 | **双模式决策树**：模式 A 首尾帧（专治形变位移） vs 模式 B 多图参考（专治对白神态）；口型动力学下颌开度限制 | 输出标准化 `StoryboardShot` 机器契约与内置 SRT 字幕 |
| **音频混音工程** | 仅零碎 BGM 提示词 | **全流程智能混音调度**：基于 `04_audio_bible.json` 动机编译 BGM Prompt、Audio Ducking 侧链避让、断崖静音 | 新增阶段 8 音频调度节点，输出精确时间码避让表与 NLE 轨道规范 |

---

## 4. 基于 LangGraph 的新一代两程九阶架构设计

### 4.1 主状态机拓扑 (Parent Graph)

```python
from langgraph.graph import StateGraph, START, END

def build_two_journey_master_graph():
    builder = StateGraph(IndustrialDramaMasterState)
    
    # ---------------- 第一程：文学故事工程节点 ----------------
    builder.add_node("stage1_ideation", stage1_ideation_node)
    builder.add_node("stage2_character", stage2_character_node)
    builder.add_node("stage3_environment_prop", stage3_environment_prop_node)
    builder.add_node("stage4_outline", stage4_outline_node)
    builder.add_node("stage5_mini_arc_screenplay", stage5_mini_arc_screenplay_node)
    builder.add_node("first_journey_gatekeeper", first_journey_gatekeeper_node)
    
    # ---------------- 第二程：视听资产与分镜工程单集微循环 ----------------
    builder.add_node("stage6_asset_prep", stage6_asset_prep_node)
    builder.add_node("stage7_storyboard", stage7_storyboard_node)
    builder.add_node("stage8_audio_mastering", stage8_audio_mastering_node)
    builder.add_node("episode_loop_increment", episode_loop_increment_node)
    builder.add_node("finalize_delivery", finalize_delivery_node)
    
    # 编排第一程线性主干与红蓝判定
    builder.add_edge(START, "stage1_ideation")
    builder.add_conditional_edges("stage1_ideation", audit_router("stage1"), ["stage1_ideation", "stage2_character"])
    builder.add_conditional_edges("stage2_character", audit_router("stage2"), ["stage2_character", "stage3_environment_prop"])
    builder.add_conditional_edges("stage3_environment_prop", audit_router("stage3"), ["stage3_environment_prop", "stage4_outline"])
    builder.add_conditional_edges("stage4_outline", audit_router("stage4"), ["stage4_outline", "stage5_mini_arc_screenplay"])
    
    # 阶段 5 波次循环推进
    builder.add_conditional_edges(
        "stage5_mini_arc_screenplay",
        mini_arc_batch_router,
        ["stage5_mini_arc_screenplay", "first_journey_gatekeeper"]
    )
    
    # 第一程定稿门控 (HITL 审批) ➔ 步入第二程
    builder.add_edge("first_journey_gatekeeper", "stage6_asset_prep")
    
    # 第二程单集微循环：6 ➔ 7 ➔ 8 ➔ 判断集数推进
    builder.add_conditional_edges("stage6_asset_prep", audit_router("stage6"), ["stage6_asset_prep", "stage7_storyboard"])
    builder.add_conditional_edges("stage7_storyboard", audit_router("stage7"), ["stage7_storyboard", "stage8_audio_mastering"])
    builder.add_conditional_edges("stage8_audio_mastering", audit_router("stage8"), ["stage8_audio_mastering", "episode_loop_increment"])
    
    builder.add_conditional_edges(
        "episode_loop_increment",
        episode_loop_router,
        ["stage6_asset_prep", "finalize_delivery"]
    )
    
    builder.add_edge("finalize_delivery", END)
    return builder.compile()
```

### 4.2 核心节点设计规范

#### 阶段 1 节点 (`stage1_ideation_node`)
* 提示词注入四大商业维度（反常识反差、极端悬念、物证讽刺、黑化反杀），产出 6-8 个爆款候选片名；
* 注入 10 大俗套禁令 + 3 大廉价爽点母集；
* 输出 Logline、Dramatic Irony 核心讽刺与全剧终极核爆点；
* 运行红蓝对抗 Agent，产出 `RedBlueAuditReport`；
* 提取并封装 `short_memory_a`（人设禁令子集 + 核心讽刺）。

#### 阶段 2 节点 (`stage2_character_node`)
* 读取 `01_bible.json` 与 `short_memory_a`；
* 强制为核心角色建立**心理动力学四元组**（Want / Need / Lie / Ghost - 注入致命缺陷）；
* 提取生活阶层轨迹、语言指纹（口头禅、防御用语、绝对不说的词）与随身标志性旧物；
* 红蓝对抗排查：动机虚浮排查、语言指纹同质化排查、道德两难撕裂度质询；
* 提取并封装 `short_memory_b`（角色活动轨迹与随身旧物）。

#### 阶段 3 节点 (`stage3_environment_prop_node`)
* 读取 `01_bible.json`、`02_characters.json` 与 `short_memory_b`；
* 核心空间规划三层做旧架构（建筑结构层 + 生活做旧霉斑划痕层 + 光影空气介质）；
* 核心反转物证规划破损形态、物理阻力参数与 +3dB 拟音；
* 红蓝对抗排查：道具工具人倾向、物理交互破坏可信度；
* 提取并封装 `short_memory_c`（大纲冲突要素包）。

#### 阶段 4 节点 (`stage4_outline_node`)
* 锁定全剧 3 大具象主题音乐动机母库（配器、BPM、调性、戏剧功能），写入 `audio_bible`（落盘 `04_audio_bible.json`）；
* 输出全季各集工笔级微观任务卡：前 3s Hook、40-60s 微反转、表面借口 vs 真实企图潜台词、集尾绝杀断点；
* 红蓝对抗深度排查：注水集中段塌陷（Filler）、微反转廉价与反派降智、断点诈骗、张力波浪图；
* 提取并封装 `short_memory_d`（全季分集剧作路线图）。

#### 阶段 5 节点 (`stage5_mini_arc_screenplay_node`)
* 以 3-4 集为一个完整的戏剧波浪单元（Mini-Arc）集中交付标准 JSON 数组；
* 动笔前三大事前安全护栏锁固化：`subtext_matrix`（表面掩饰 vs 隐藏企图，3-5 个禁词）、`friction_and_cost_preset`（肉体/利益代价与现实物理毛刺）、`detailed_causal_task`；
* 单元内集间 0 秒物理咬合：自动提取前一集 `episode_end_physical_delta`，注入后一集 `previous_episode_physical_pickup`；
* 循环流转：当当前波次完成且未达总集数时，推进到下一波次；全季完成后流向 `first_journey_gatekeeper`。

#### 第一程定稿门控 (`first_journey_gatekeeper`)
* 声明式中断 `interrupt_after=["first_journey_gatekeeper"]`；
* 前端展示全季文学定稿看板，创作者审阅通过后确认定稿加锁；
* 锁死全季文学剧本，置位 `literary_journey_locked = True`，初始化 `current_visual_episode = 1`，解锁第二程。

#### 阶段 6 节点 (`stage6_asset_prep_node`)
* 扫描当前集文学稿 `episodes_screenplay/ep_XX.json` 的出场角色、场景、道具与声音需求；
* 查询全局真理源 `05_visual_audio_assets.json`：
  - `APPROVED` 资产直接复用并沿用原 `asset_id`；
  - 发生负伤/湿身/换装时建立状态分支 `CHAR_<ID>_STATUS_<STATE>`；
  - 缺失项按需触发单项生成（四视图全身独立无裁切、剧本实际微表情、核心物证破坏态双图）；
* 输出**本集视听资源引单 (Episode Resource Manifest)**：按角色（一/二/三级）、场景（主/次）、道具（一/二/三级）、声音清晰引单；
* 红蓝对抗审查：排查 AI 假人感、微表情剧本相关性、资产冗余度；
* 触发阶段 6 审查门控。

#### 阶段 7 节点 (`stage7_storyboard_node`)
* 读取当前集文学稿 + 阶段 6 资源引单 + 上一集分镜最后一秒物理快照；
* **双模式选型黄金决策树**：
  - **模式 A 首尾帧 (`first_last_frame`)**：涉及形变、破坏、猛烈位移；必须配置首帧 Prompt + 尾帧 Prompt + 视频运动 Prompt；严禁用于对白神态；
  - **模式 B 多图参考 (`multi_image_reference`)**：涉及对白、微表情、过肩对峙；必须配置参考资产 ID 数组 + 多图生视频 Prompt；
* **全息声学指令与口型动力学**：
  - 对白注入声纹 ID、声带闭合腔体指令与呼吸停顿；
  - 拟音 Foley 标注 +2dB~+3dB 增益；
  - 严格限制下颌开度 `jaw_open_scale`（0.4~0.5 咬牙 vs 0.8~0.9 呼喊）；
* 产出结构化单镜头 JSON 契约 + 内置毫秒级标准 SRT 字幕；
* 触发阶段 7 审查门控。

#### 阶段 8 节点 (`stage8_audio_mastering_node`)
* 读取 `04_audio_bible.json` 主题动机母库 + 阶段 7 绝对毫秒时间轴与 SRT 掩码；
* 动态编译分段 BGM Prompt（锁定 120s，按 Hook/反转/断点切片，适配 Suno/Udio）；
* 计算动态侧链避让曲线（对白区间 BGM 自动衰减至 `-18dB ~ -22dB`，悬疑动作区拉升至 `-10dB ~ -12dB`）；
* 核心微反转点强制插入 2-3 秒 `-inf dB` 绝对断崖静音；
* 断点黑屏骤停，无拖音拖尾；
* 输出 NLE 剪辑轨道指南（Track A1/A2/A3/V1）；
* 触发阶段 8 单集结项门控。

#### 单集微循环路由器 (`episode_loop_router`)
* 若 `current_visual_episode < total_episodes`：提取当前集集尾物理快照，`current_visual_episode += 1`，跳转回 `stage6_asset_prep`；
* 若 `current_visual_episode == total_episodes`：全流程结束，走向交付节点。

---

## 5. 红蓝对抗 AI 自审与门控拦截机制

### 5.1 双视角审核体系

```
       [待交付产物] (剧本/资产/分镜/混音)
             │
             ├──► 【蓝军: 客观合规审查员】──► 核查硬指标 (时间轴、格式、禁令红线)
             │
             └──► 【红军: 魔鬼挑刺制片人】──► 专挑暗刺 (逻辑降智、说教台词、AI穿模融化)
                         │
                         ▼
                  [综合裁决与分级]
                  ├── 🔴 RED_BLOCKING  ──► 自动拦截，状态机原位重构
                  └── 🟡 YELLOW_WARNING ──► 呈报前端 HITL 门控，主创裁决是否采纳
```

### 5.2 状态机中的拦截实现

```python
def audit_router(stage_name: str):
    def _route(state: IndustrialDramaMasterState) -> str:
        report = state.latest_audit
        if report.verdict == AuditVerdict.RED_BLOCKING:
            logger.warning(f"阶段 {stage_name} 发现阻断级缺陷，自动重试修补: {report.blocking_issues}")
            return f"{stage_name}"  # 回流重写
        # 绿色放行或黄色警示均前进至下一步（黄色警示在 HITL 门控由人工裁决）
        next_map = {
            "stage1": "stage2_character",
            "stage2": "stage3_environment_prop",
            "stage3": "stage4_outline",
            "stage4": "stage5_mini_arc_screenplay",
            "stage6": "stage7_storyboard",
            "stage7": "stage8_audio_mastering",
            "stage8": "episode_loop_increment",
        }
        return next_map.get(stage_name, "finalize_delivery")
    return _route
```

---

## 6. 数据库 Schema 升级与持久化契约

### 6.1 核心数据表扩展

1. **`dramas` 表**：
   - 增加 `journey_state`: `ENUM('JOURNEY_1_LITERARY', 'JOURNEY_2_VISUAL', 'COMPLETED')`；
   - 增加 `literary_locked`: `BOOLEAN DEFAULT FALSE`；
   - 增加 `candidate_titles_json`: 存储四大维度爆款片名；
   - 增加 `double_track_prohibitions_json`: 存储 10 大俗套与 3 大廉价禁令；
   - 增加 `audio_bible_json`: 存储全剧 3 大主题音乐动机。
2. **`characters` 表**：
   - 增加 `psychological_quad_json`: 存储 `want`, `need`, `lie`, `ghost`；
   - 增加 `linguistic_fingerprint_json`: 存储口头禅、防御用语、禁词；
   - 增加 `anchor_props_json`: 存储随身标志性旧物。
3. **`scenes` 表**：
   - 增加 `weathering_layers_json`: 存储建筑结构、生活做旧霉斑、光影微尘三层规划；
   - 增加 `scene_tier`: `INT` (1: 核心主场景, 2: 过渡次场景)。
4. **`visual_audio_assets` 表（新增，对应 `05_visual_audio_assets.json`）**：
   - 字段：`id`, `drama_id`, `asset_id`, `category` (character/scene/prop/tts), `tier` (1/2/3), `status` (APPROVED/REJECTED), `source_ref_id`, `style_profile`, `aspect_ratio`, `prompt_payload`, `media_url`。
5. **`storyboards` 表（升级至工业执行契约）**：
   - 增加 `generation_mode`: `VARCHAR(32)` (`first_last_frame` / `multi_image_reference`)；
   - 增加 `first_last_config_json`: 首尾帧 Prompt 与运动指令；
   - 增加 `multi_image_config_json`: 参考素材 ID 数组与多图 Prompt；
   - 增加 `audio_holographic_json`: 声纹腔体指令与拟音增益；
   - 增加 `lipsync_dynamics_json`: 下颌开度、嘴角张力；
   - 增加 `srt_export_text`: 本镜关联 SRT 文本。
6. **`audio_masterings` 表（新增，对应阶段 8 产物）**：
   - 字段：`id`, `drama_id`, `episode_id`, `bgm_full_prompt`, `ducking_schedule_json`, `nle_guidelines_json`, `audit_report_json`。

---

## 7. 前端 UI 与交互工作流演进

### 7.1 双程导航布局重构

在 [ScriptStudioView.vue](f:/code/LocalMiniDrama/frontweb/src/views/ScriptStudioView.vue) 中，将原平铺的 5 个 Tab 重组为两程九阶架构：

```
左侧导航侧边栏
├── 🎬 【第一程：文学故事工程】(全季故事闭环)
│   ├── 1️⃣ 阶段 1：题材破壁 (候选片名矩阵 / 负向双轨禁令 / 终局核爆点)
│   ├── 2️⃣ 阶段 2：角色建模 (心理四元组 / 语言行为指纹 / 随身旧物)
│   ├── 3️⃣ 阶段 3：空间物证 (场景三层做旧 / 反转道具与+3dB拟音)
│   ├── 4️⃣ 阶段 4：大纲与动机 (全剧 3 套音乐动机 / 工笔级因果任务卡)
│   └── 5️⃣ 阶段 5：文学剧本波次吞吐 (3-4集/波 Mini-Arc 看板，集间物理咬合快照)
│   └── 🔒 【第一程全季文学定稿锁】(点击锁定全季剧本，解锁第二程)
│
└── 🎥 【第二程：视听资产与分镜工程】(单集微循环滚动)
    └── 🔄 第 [ 01 / 12 ] 集微循环工作台
        ├── 6️⃣ 本集资产准备 (本集视听资源引单 Manifest / 增量单项素材库)
        ├── 7️⃣ 本集分镜执行表 (首尾帧 vs 多图可视化标签 / 口型动力学 / SRT 预览)
        ├── 8️⃣ 本集混音工程 (BGM Prompt 卡片 / Ducking 分贝避让表 / 断崖静音卡点)
        └── ⏭️ 【确认结项并推进下一集】(提取集尾快照 ➔ 步入 Ep 02)
```

### 7.2 红蓝对抗自审悬浮卡片 (`RedBlueAuditCard.vue`)
* 每次阶段生成或修补完毕，界面右下角浮现红蓝对抗卡片；
* 蓝军面板展示客观合规指标打勾情况；
* 红军面板高亮魔鬼挑刺细节；
* 若为 🔴 Blocking：提示“正在就地重构”；若为 🟡 Warning：提供【采纳优化建议】与【忽略挑刺并放行】选项。

---

## 8. 改造实施里程碑与演进计划

1. **第一阶段：契约层与状态模型升级 (Phase 1)**
   - 扩展 `script_graph_state.py`，新增 `IndustrialDramaMasterState`、`RedBlueAuditReport`、`StoryboardShot` 等数据模型；
   - 编写单元测试验证 Schema 完整性与序列化性能。
2. **第二阶段：第一程文学工程流水线重构 (Phase 2)**
   - 升级阶段 1~4 提示词与节点逻辑，引入双轨禁令母集与全剧音乐主题动机；
   - 重构阶段 5 为 Mini-Arc 戏剧波次吞吐，实现集间物理快照 0 秒咬合；
   - 实现红蓝对抗自审 Agent 与 Blocking 自动重构路由；
   - 实现第一程定稿门禁节点。
3. **第三阶段：第二程单集微循环流水线实现 (Phase 3)**
   - 实现阶段 6 资产扫描器、`05_visual_audio_assets.json` 真理源注册与本集资源引单；
   - 实现阶段 7 首尾帧 vs 多图决策树、口型动力学下颌开度约束与 SRT 导出；
   - 实现阶段 8 BGM 分段 Prompt 编译、侧链 Ducking 避让与断崖静音调度；
   - 构建单集滚动推进路由器。
4. **第四阶段：前后端 API 与视图交互联调 (Phase 4)**
   - 扩展 FastAPI 端点与 SSE 事件流，支持单集微循环状态推送；
   - 重构 `ScriptStudioView.vue` 界面与红蓝挑刺交互面板；
   - 进行全季 12 集样板短剧全流程自动化测试与质量回归。
