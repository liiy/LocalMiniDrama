---
name: screenplay-pipeline
description: 通用AI原创连续剧短剧工业化生产管线。当用户想要创作、生成、编写短剧、剧本、分镜或分集大纲时触发（例如：写短剧, 剧本创作, AI短剧, 生成分镜, 连续剧剧本, 短剧大纲, 短剧人物设定, 短剧立项）。采用两程九阶工业架构（第一程全季文学剧本疾速波次定稿闭环 ➔ 第二程多模态视听基准资产按需准备 ➔ 逐集单镜头整秒分镜与全息声画JSON生成，带SRT字幕、单集物理快照接力与NLE混音调度）。
version: 10.0.0
---
# AI 原创连续剧短剧工业管线标准作业程序 (AI Serial Micro-Drama Master SOP v10.0.0 - 终极工业全息闭环版)

本系统专为 AI 原创短剧打造，完全适配短剧算法逻辑。
全管线采用**“两程九阶（Two-Journey, Nine-Stage）”**工业流转体系：
* **第一程【文学故事工程】**：从题材破壁一直到**按 3-4 集戏剧高潮单元疾速完成全季文学剧本定稿**，确保全季伏笔闭环、人物关系网动态撕裂与戏剧情绪连贯；
* **第二程【视听资产与分镜工程】**：文学定稿后，按集增量准备角色（三级）、场景（两级）、道具（三级）单项资产并提取母音频，再逐集输出支持**首尾帧生视频（First-Last-Frame）**与**多图参考生视频（Multi-Image I2V）**的机器可读 JSON 分镜头执行表，内置毫秒级 SRT 字幕，并最终交付包含四大依据溯源、全量 BGM Prompt 与动态分贝避让调度表的混音工程规范。

---

## 一、 双程九阶工业架构流转全景图 (Dual-Journey Architecture)

```
====================================================================================================
【第一程：文学故事工程 (The Literary Journey)】—— 编剧室闭环，全季故事逻辑与伏笔锁死
====================================================================================================
[阶段 1: 题材破壁与创意引擎] ──► 产出: 01_bible.json (双轨禁令总母集 / 6-8个爆款片名矩阵 / 工业Logline / 终局核爆点)
          │
          ▼
[阶段 2: 角色全息人设与关系网] ─► 产出: 02_characters.json (毫米级骨相DNA / 真实生活服饰代码 / 声学人设 / 四阶段情感弧 / 双轨关系网)
          │
          ▼
[阶段 3: 空间设计与物证规划] ──► 产出: 03_environments_props.json (场景三层做旧架构 / 核心物证破损阻力规划 / 服装场景同源共振)
          │
          ▼
[阶段 4: 双螺旋分集大纲规划] ──► 产出: 04_outline.json (外部事件链+关系质变链双螺旋 / 谎言崩解度 / 全剧核心音乐动机母库)
          │
          ▼
[阶段 5: 文学剧本疾速波次产出] ─► 3-4集/波次连续吞吐并落盘: episodes_screenplay/ep_01.json ~ ep_NN.json
          │                         (极简纯文学 JSON: 动作行 Show Don't Tell / 发声呼吸括注 / 潜台词错位 / 五维时空总线)
          ▼
   🛑【第一程全季文学总揽定稿大审】(全季 12-24 集文学定稿，伏笔 100% 闭环，红军里程碑审查放行进入第二程)

====================================================================================================
【第二程：视听资产与分镜工程 (The Visual & Storyboard Journey)】—— 单集微循环流水线 (Episode Loop)
====================================================================================================
(第一程全季文学剧本全量定稿后，第二程逐集滚动闭环：)

 ┌──►【单集循环起点：第 XX 集启动】(读取当前集文学 JSON ep_XX.json 与上集物理快照)
 │        │
 │        ▼
 │   [阶段 6: 第 XX 集按需资产准备] (三级角色资产 / 两级场景 / 三级道具 / 查库复用老资产 / 增量建档 / 母音频实体化)
 │        │
 │        ▼ 🛑【阶段 6 单集资产审查门控】
 │        │
 │   [阶段 7: 第 XX 集分镜头生成与 SRT 导出] (整秒分镜 / 台词完整闭环 / 首尾帧与多图选型 / 全息声画TTS / 导出标准SRT)
 │        │
 │        ▼ 🛑【阶段 7 单集分镜审查门控】
 │        │
 │   [阶段 8: 第 XX 集多轨音频与混音调度] (四大依据溯源 / 定制Full BGM Prompt / 动态分贝避让调度表 / NLE剪辑指南)
 │        │
 │        ▼ 🛑【阶段 8 单集正式结项门控】
 │        │
 └────────┴──► 若 XX < 全季总集数：提取【集尾物理快照】，自动步入【第 XX+1 集阶段 6】！
               若 XX == 全季总集数：🛑【第二程全剧视听成片终极验收大审】，全季工程圆满交付！
```

---

## 二、 双层记忆流转机制 (全局长期档案 + 单集物理快照接力)

管线采用**“全局静态档案库（长期记忆）”**与**“单集接力数据包（短期记忆）”**的双层流转架构，彻底杜绝大模型跨集失忆、时间线错乱与道具瞬移。

### 1. 记忆双轨流转协议
* **全局长期记忆（文件系统持久化落盘）**：`01_bible.json`（基本盘/禁令）、`02_characters.json`（肖像DNA/关系网）、`03_environments_props.json`（空间道具）、`04_audio_bible.json`（动机母库）、`05_visual_audio_assets.json`（视听总库）、`episodes_screenplay/ep_XX.json`（全集文学定稿）。全剧只读共享，贯穿全季 100 集绝不漂移；
* **动态短期记忆（单集接力数据包）**：阶段间一次性交底便签（A/B/C/D/E）与单集物理快照，即用即覆。

### 2. 单集物理快照接力机制 (Physical Snapshot Relay)
为了彻底消灭跨集大模型失忆、道具瞬移、伤口自愈与时间线混乱，在每一集文学剧本 JSON (`episodes_screenplay/ep_XX.json`) 中，强制通过三大核心时空字段实现跨集物理闭环：
1. **`previous_episode_0s_pickup`（上集状态 / 0秒接棒）**：记录从上一集继承而来的时间、身体姿态、持有道具与伤势，作为本集开篇第 1 行动作行的动量起点；
2. **`golden_cliffhanger_hook`（本集结尾黄金悬念钩子）**：物理危机动作 + 绝杀对白 + 声学骤停标记，逼出观众滑屏欲望；
3. **`episode_end_physical_delta`（本集尾物理状态快照）**：将本集最后一秒的真实世界状态完整封存（包含时间线进度、身体姿态、手持道具位置与伤势、环境与天气），作为给下一集的物理交接棒：

```json
"episode_end_physical_delta": {
  "timeline_progress": "故事主时间线第 2 天清晨 06:30，距离周氏集团借壳上市答辩倒计时还剩 41 小时",
  "character_pose": "林晚双膝半跪在厨房泥水里，右手手背撑地带发黑盐霜，小臂有轻微挫伤，大衣第二颗纽扣线头松脱2cm",
  "held_props_and_injuries": "林晚右手掌心沾满褐色盐霜，带血日记撕页与药盒纸片贴身焐在胸口大衣内袋，生锈老铜钥匙系在红绳挂在胸前；周衍右手握持磨砂煤油打火机",
  "environment_and_weather": "旧公房厨房角落，15W节能灯惨绿频闪，窗外深秋冻雨转为清晨浓雾，地面积水泛潮"
}
```

#### 跨阶段消费契约：
1. **向阶段 5 下一集传递** ➔ 1:1 转化为第 N+1 集的 `previous_episode_0s_pickup`；
2. **向阶段 6 资产系统传递** ➔ 读取 `held_props_and_injuries` 中的伤势，自动生成 `[TAG: CHAR_STATUS_INJURED]` 负伤状态分支生图 Prompt；
3. **向阶段 7 分镜系统传递** ➔ 强制将快照绑定为第 N+1 集第 01 镜的【首帧垫图 (First Frame Prompt)】，实现跨集画面 0 毫秒跳帧、一镜到底！

---

## 三、 全剧资产四段式确定性命名与寻址协议 (Deterministic Asset Naming Protocol)

全管线的所有多模态资产（阶段 6 图生图生成与阶段 7 分镜槽位引用），必须 100% 严格遵循以下四段式命名公式，严禁自造任何非标准 ID：

$$\text{资产 ID} = \text{\textbf{[大类前缀]}} \_ \text{\textbf{[对象英文标识]}} \_ \text{\textbf{[等级/分层]}} \_ \text{\textbf{[功能类型/状态修饰符]}}$$

### 1. 命名空间枚举规范 (Namespace Tokens)
* **大类前缀 (Category)**：`CHAR_` (角色), `ENV_` (场景), `PROP_` (道具), `VOICE_` (声音)
* **等级分层 (Tier)**：`T1` (一级基础/主场景/核心物证), `T2` (二级表现/过渡场景/锚定物), `T3` (三级专项/环境杂物)

### 2. 标准资产 ID 映射索引速查表 (Asset ID Syntax Table)
| 资产物理类型 | 标准资产 ID 命名公式 (Asset ID Formula) | 示例 | 阶段 6 图生图底图来源 / 阶段 7 槽位装配场景 |
|---|---|---|---|
| **角色 0 号基准肖像** | `CHAR_<NAME>_T1_BASE_PORTRAIT` | `CHAR_LINWAN_T1_BASE_PORTRAIT` | 文生图 T2I 初始生成，全剧唯一 0 号人脸基因源！ |
| **角色全身基础定妆** | `CHAR_<NAME>_T1_BASE_COSTUME` | `CHAR_LINWAN_T1_BASE_COSTUME` | 以 `BASE_PORTRAIT` 为底图 I2I 扩展 (Denoise 0.45)，全身从头到脚定妆 |
| **四角度全身视图** | `CHAR_<NAME>_T2_4V_<FRONT/PROFILE/3Q/BACK>` | `CHAR_LINWAN_T2_4V_PROFILE` | 以 `BASE_COSTUME` 为底图，ControlNet 姿态旋转 (Denoise 0.35~0.45) |
| **剧本实际情绪图** | `CHAR_<NAME>_T2_EXP_<EMOTION>` | `CHAR_LINWAN_T2_EXP_GRIEF` | 以 `BASE_PORTRAIT` 为底图局部重绘 Inpainting (Denoise 0.40) |
| **极端光感测试图** | `CHAR_<NAME>_T2_LIGHT_<TYPE>` | `CHAR_LINWAN_T2_LIGHT_LOWKEY` | 以 `BASE_PORTRAIT` 为底图 Relighting 重光照 (Denoise 0.35) |
| **生理微距特写图** | `CHAR_<NAME>_T3_MACRO_<HAND/EYE/MOUTH>` | `CHAR_LINWAN_T3_MACRO_HAND` | 从 `BASE_COSTUME` 局部裁剪放大 (Denoise 0.50)，锁死创可贴/戒指 |
| **负伤/战损状态分支** | `CHAR_<NAME>_T3_STATUS_<INJURY>[_EPXX]` | `CHAR_LINWAN_T3_STATUS_INJURED` | 以 `BASE_COSTUME` 为底图局部重绘叠加淤青血渍 (Denoise 0.40) |
| **角色专属母音频** | `VOICE_<NAME>_MASTER` | `VOICE_LINWAN_MASTER` | 从定稿剧本抓取高光金句 + 1:1 翻译阶段 2 腔体人设生成的母音频 (.wav) |
| **主场景全景建立图** | `ENV_<SCENE>_T1_WIDE` | `ENV_01_T1_WIDE` | 纯文生图 T2I，大远景建立分镜垫图 |
| **主场景过肩景深板** | `ENV_<SCENE>_T1_OTS_BG` | `ENV_01_T1_OTS_BG` | 以 `ENV_WIDE` 为底图执行 Depth Blur I2I (Denoise 0.3)，对白背景垫图 |
| **主场景空间空镜** | `ENV_<SCENE>_T1_INSERT_<PROP>` | `ENV_01_T1_INSERT_CLOCK` | 以 `ENV_WIDE` 局部特写放大，静物特写分镜垫图 |
| **主场景时态分支** | `ENV_<SCENE>_T1_STATE_<TIME/DAMAGE>` | `ENV_01_T1_STATE_NIGHT` | 以 `ENV_WIDE` 为底图 ControlNet 锁结构变换色温与天气 |
| **过渡次场景关键帧** | `ENV_<SCENE>_T2_KEYFRAME` | `ENV_02_T2_KEYFRAME` | 单张过渡背景分镜垫图 (T2I) |
| **核心物证静态初始态**| `PROP_<ITEM>_T1_STATIC` | `PROP_01_T1_STATIC` | 纯文生图 T2I，模式 A 首帧垫图 / 手持查看微距 |
| **核心物证破坏交互态**| `PROP_<ITEM>_T1_ACTION` | `PROP_01_T1_ACTION` | 以 `PROP_STATIC` 为底图 Inpainting 局部重绘 (Denoise 0.5)，模式 A 尾帧垫图 |

### 3. 极端大规模剧集修饰符扩展协议 (Extended Modifiers for Large Series)
当短剧规模达 60-80 集出现复杂分支时，允许在第四段追加标准修饰符，确保命名空间绝对隔离、零冲突：
* 角色多次换装：`CHAR_LINWAN_T2_COSTUME_GOWN_NIGHT`
* 角色多次负伤：`CHAR_LINWAN_T3_STATUS_INJURED_EP45`
* 道具多次损毁：`PROP_LETTER_T1_ACTION_BURNT`
* 场景严重剧变：`ENV_FACTORY_T1_STATE_EXPLODED`

---

## 四、 红蓝对抗 AI 质量自审与 10 大全量哨卡机制 (Full-Lifecycle Adversarial Audit Matrix)

管线强制由**【蓝军（合规审查员 / Compliance Officer）】**与**【红军（魔鬼制片人 / 苛刻影评人 Red-Team Critic）】**在全流程设立 10 大审判哨卡。为了保证跨模型可移植性，所有大模型在执行各阶段时必须严格对照下表执行 100% 穷尽核验：

### 1. 10 大全生命周期红蓝自审项目全量清单矩阵 (Exhaustive Audit Matrix)
| 阶段 / 哨卡序号 | 蓝军客观合规审查清单 (必须 100% 达标打勾项) | 红军魔鬼制片人挑刺清单 (专门排查隐性内伤，严禁夸奖) | 阻断与流转规则 |
|---|---|---|---|
| **[哨卡 1] 阶段 1：题材破壁** | 1. 10大老套因果禁令清单完备性<br>2. 3大廉价爽点禁令完备性<br>3. 6-8个候选片名覆盖四大商业维度<br>4. Logline 工业公式与终局核爆点对称 | 1. **概念假大空排查**（主角动机是否自嗨脱离现实）<br>2. **对抗力量单薄挑刺**（反派是否太弱缺乏压迫感）<br>3. **片名俗套倾向挑刺**（是否有土味网文低端感） | 🔴 假大空直接阻断重写<br>🟡 挑刺方案由主创裁决 |
| **[哨卡 2] 阶段 2：角色建模** | 1. **生理性别强制必填** (防性别幻觉与配音错乱)<br>2. 毫米级骨相 DNA 与面部瑕疵坐标<br>3. 从头到脚生活质感服饰材质与松脱线头<br>4. 声学人设发声腔体与发干瑕疵<br>5. 心理四元组与双轨关系网完备 | 1. **人设动机虚浮排查**（Want与Need是否生死冲突）<br>2. **语言指纹同质化排查**（是否所有人说话口吻雷同）<br>3. **道德两难撕裂度质询**（利益死结是否真正肉痛） | 🔴 动机悬浮/同质化阻断重写<br>🟡 语言润色由主创裁决 |
| **[哨卡 3] 阶段 3：空间道具** | 1. 场景结构/霉斑划痕/微尘三层做旧完备<br>2. **场景与服装同源共振检查** (严禁干净样板房)<br>3. 核心物证破损尺度与物理阻力参数<br>4. 核心道具专属 +3.0dB 拟音标记 | 1. **道具机械工具人排查**（物证保存是否违背常理）<br>2. **场景生活腐殖质排查**（是否缺乏底层小城压迫感）<br>3. **物理破坏可信度质询**（形变是否符合材质学） | 🔴 万能神级道具阻断重写<br>🟡 做旧细节由主创裁决 |
| **[哨卡 4] 阶段 4：分集大纲** | 1. 全季总集数达标，单集时长精准对齐<br>2. 全剧 3 大音乐主题动机母库完备<br>3. 双螺旋任务卡（外部事件+关系质变点）<br>4. 每集前3s Hook、45s微反转、断点字段完备 | 1. **注水集排查**（哪一集去掉对主线无影响，强制删并）<br>2. **微反转廉价度排查**（反派是否降智配合）<br>3. **断点诈骗排查**（是否存在做梦惊醒虚空悬念）<br>4. **全季张力波浪图平缓挑刺** | 🔴 注水/断点诈骗强制阻断重写<br>🟡 反转加码由主创裁决 |
| **[哨卡 5] 阶段 5：文学剧本** | 1. 全篇 Show Don't Tell，零心理描写<br>2. 对白发声物理阻力括注 100% 完备<br>3. 三大戏剧声学行为标记嵌入<br>4. 五维全息时空总线字段 100% 完备 | 1. **潜台词冰山测试**（排查嘴替大白话说教，给改写方案）<br>2. **道德与肉体代价拷问**（主角是否无代价通关）<br>3. **反派智商与压迫感质询**（反派是否被动挨打）<br>4. **现实毛刺排查**（是否缺少打火机卡壳/暴雨打断）<br>5. **关系网断层与情感失忆排查** | 🔴 说教嘴替/无代价阻断重写<br>🟡 潜台词方案由主创裁决 |
| **🛑【里程碑大审 1】第一程文学定稿总审** | 1. 全季 12-24 集文学 JSON 100% 交付<br>2. 集与集之间五维时空总线 100% 咬合 | 1. **全季伏笔回收率大审**（前几集线索是否全部解开）<br>2. **中段危机与灵魂暗夜真伪大审**<br>3. **主角精神救赎与终局核爆对齐大审** | 🔴 伏笔断头强制回溯修改<br>🟢 放行进入第二程 |
| **[哨卡 6] 阶段 6：资产准备** | 1. 角色三级、场景两级、道具三级归类完备<br>2. 已有 APPROVED 资产 100% 继承复用<br>3. 图生图底图来源与重绘幅度明确标注<br>4. 母音频金句与跨平台 TTS Prompt 完备 | 1. **AI 假人塑料感与网红磨皮排查**<br>2. **四视图从头到脚绝对全身检查** (严禁脚底裁切)<br>3. **微表情剧本相关性挑刺** (严禁无依据大笑/大哭)<br>4. **资产冗余度挑刺** (排查未调用图片/三级杂物生图) | 🔴 假人/缺脚强制重生成<br>🟡 质感微调由主创裁决 |
| **[哨卡 7] 阶段 7：单镜头分镜** | 1. **单镜头时长必须为绝对整秒** (2s/3s/4s/5s/6s/7s，单镜上限7.0s)<br>2. **全集秒数累加与规划总时长绝对误差 $\le$ 6.0s** (允许 $\pm$6.0s 弹性区间，如120s规划 ➔ 114.0s~126.0s 均合规放行，严禁强行凑整)<br>3. **台词语义完整闭环** (切镜前留出0.4s缓冲)<br>4. SRT 时间码包络于镜头内，精准顺延发声入点偏移，无跨镜漂移<br>5. 仅引用 APPROVED 单项素材，无未裁切大图<br>6. **模式B多模态提示词100%合规**（先@后描述、按叙事时序、关键约束前置、具体动词、图音独立计数、音频极简不写口型/眨眼、符合目标模型Wan3.0/Seedance/MiniMax台词语法、9项自检全部通过） | 1. **AI 视频模型穿模融化风险挑刺** (复杂交互建议拆分)<br>2. **视听节奏与景别对称单调挑刺**<br>3. **提示词违规排查**（排查抽象指代、后置括号、多动作堆砌、冗余语速/口型指令） | 🔴 半截话/碎秒/超时6秒/提示词语法违规阻断<br>🟡 穿模风险提示供拍摄留意 |
| **[哨卡 8] 阶段 8：混音调度** | 1. 四大依据溯源完整性 (动机/时长/对白码/断点)<br>2. 广播级响度锁定 `-23 LUFS` 标准<br>3. 调度表对白避让 `-20dB`，微反转绝对静音 `-∞ dB`<br>4. BGM 在最后 2 秒平滑淡出，片尾骤停 | 1. **BGM 喧宾夺主排查** (配器是否遮蔽重要耳语)<br>2. **反转静音反差锐度挑刺** (进出是否足够锋利吓人)<br>3. **集尾下潜重音拖音泄气挑刺** (随黑屏硬切无拖尾) | 🔴 响度违规/无静音阻断重写<br>🟡 混音微调由主创裁决 |
| **🛑【里程碑大审 2】第二程成片终审** | 1. 全季分镜 JSON、SRT 字幕、混音调度表完备<br>2. 全剧多模态资产注册表版本统一 | 1. **跨集人物视觉一致性总审** (零换脸、零换装)<br>2. **全剧视听声场与节奏波浪总审**<br>3. **交付成片可执行性终极验收** | 🔴 资产漂移打回修正<br>🟢 全季工程圆满交付！ |

### 2. 双轨流转纪律 (Dual-Track Failover Rules)
* 🔴 **Blocking（阻断级硬伤）**：只要命中上述红线（如假人脸、台词半截话、断点诈骗、注水集），门控强制拒绝放行，大模型必须在当前阶段自动就地重写自愈，直至降级为 🟢 或 🟡；
* 🟡 **Warning（刺痛改进建议）**：红军指出潜台词不够隐晦、视频轻微穿模风险等审美/工艺建议，门控动态赋权，由人类主创一键选择【采纳修改】或【回复“确认无误，忽略挑刺”】。

---

## 五、 全阶段四维元协议与执行规范 (Stage 1 ~ Stage 8)

每个阶段均强制执行**【1. 输入契约 ➔ 2. 内部思考协议 (CoT) ➔ 3. 生产与排异规则 ➔ 4. 输出数据契约】**四维标准：

### 【第一程：文学故事工程】

#### 阶段 1：题材破壁与创意引擎 (Ideation & Premise)
* **1. 输入契约**：用户初始输入的 7 项基本盘（题材/类型/风格/单集基准时长/总集数/画幅/目标视频引擎 `target_video_engine`（缺省值 `"wan3.0"`，可选 `"seedance2.5"`, `"minimax_h3"`）/故事概要）。
* **2. 内部思考协议 (CoT)**：
  - Step 1: 穷举该题材当下最泛滥的 10 个老套因果与 3 个低幼打脸爽点；
  - Step 2: 依据“突发危机+致命缺陷+倒计时+毁灭代价”公式锻造核心 Logline；
  - Step 3: 推导全剧终局核爆点（Grand Payoff）与核心讽刺（The Irony）；
  - Step 4: 脑暴覆盖四大商业维度的 6-8 个爆款候选片名矩阵。
* **3. 生产与排异规则**：严禁伟光正孤勇主角；严禁非黑即白反派；严禁假大空大团圆。
* **4. 输出数据契约**：标准 Markdown 报表，写入 `01_bible.json`，附带红蓝自审与片名敲定门控。

#### 阶段 2：角色人设、动态情感弧与双轨关系网建模 (Character Engine)
* **1. 输入契约**：`01_bible.json` + 【短期记忆 A：人设禁令子集 + 核心讽刺】。
* **2. 内部思考协议 (CoT)**：
  - Step 1: 声明生理性别，为角色注入基于核心讽刺的“致命谎言 (The Lie)”与自私心理缺陷；
  - Step 2: 推导生物骨相 DNA（高颧骨/内双/毫米级痣坐标）与从头到脚真实生活质感服化道代码（面料克重/线头松脱/起球泥斑）；
  - Step 3: 确立文字级声学人设（发声腔体位置、声带发干瑕疵、语速基频）；
  - Step 4: 构建角色对之间的【深层情感羁绊】、【生死利益死结】与【共同生活旧情物证】；
  - Step 5: 规划全季四阶段（防御 ➔ 裂痕 ➔ 深渊 ➔ 和解）动态情感流转曲线。
* **3. 生产与排异规则**：必须包含生理性别；骨相与瑕疵必须精确到毫米；服化道严禁崭新塑料布；必须提取旧情物证。
* **4. 输出数据契约**：结构化人设与双轨关系矩阵，写入 `02_characters.json`。

#### 阶段 3：空间设计与物证规划 (Environments & Props Planning)
* **1. 输入契约**：`01_bible.json` + `02_characters.json` + 【短期记忆 B】。
* **2. 内部思考协议 (CoT)**：
  - Step 1: 规划一级核心主场景（发生>=3场）与二级过渡次场景；
  - Step 2: 依据【场景与服装同源共振铁律】，使空间破损脏旧度与角色服装磨损度 100% 同频；
  - Step 3: 承接角色随身旧物，规划一级核心物证的叙事隐喻、破损形态与物理阻力。
* **3. 生产与排异规则**：严禁干净样板房（强制结构/水渍霉斑/光影微尘三层做旧）；严禁万能 GPS 解密道具；道具必须标注物理阻力与 +3dB 拟音。
* **4. 输出数据契约**：结构化空间与道具档案，写入 `03_environments_props.json`。

#### 阶段 4：双螺旋分集大纲与全剧核心音乐动机母库 (Outlines & Leitmotif Registry)
* **1. 输入契约**：`01_bible.json` (核爆点/禁令) + `02_characters.json` (情感弧/关系网) + `03_environments_props.json` + 【短期记忆 C】。
* **2. 内部思考协议 (CoT)**：
  - Step 1: 规划全剧 3 个核心音乐主题动机母库 (Leitmotif Registry：动机A压迫/动机B创伤/动机C反杀)；
  - Step 2: 将全季按 3-4 集划分为若干戏剧小高潮单元 (Mini-Arcs)；
  - Step 3: 逐集构建【外部事件链 (Plot)】与【核心关系质变点 (Relational Shift)】双螺旋；
  - Step 4: 逐集计算主角心理谎言崩解度 (Lie Erosion) 与集尾绝杀断点。
* **3. 生产与排异规则**：微反转必须优先调用阶段 2 身体伤痕或服饰破绽；严禁注水集与断点诈骗；所有伏笔最终向阶段 1 核爆点收敛。
* **4. 输出数据契约**：全集双螺旋工笔任务卡与音乐母库，写入 `04_outline.json`。

#### 阶段 5：全季原剧文学剧本疾速波次连续吞吐 (Turbo Mini-Arc Batching & JSON Contract)
* **1. 输入契约**：`04_outline.json` (工笔任务卡) + `01`双轨禁令 + `02`骨相服饰关系网 + `03`空间物证 + 上一集物理快照 (`previous_episode_0s_pickup` / `episode_end_physical_delta`)。
* **2. 内部思考协议 (CoT)**：
  - Step 1: 动笔前隐式加载三大护栏（潜台词错位、全场禁词、主角代价与现实毛刺）；
  - Step 1.5: 【物理空间标头与单核演进】单集必须规划 **2 ~ 4 个标准时空场景标头**（如 `【场景 01】外景. 太平间后门 - 晨`），严禁无标头混沌长篇；单个视听动作行贯彻单核心物理动作演化，长台词自然换行分段，从文学源头为下游阶段七的“场景级切片吞吐”与“单动作视频提示词”提供天然适配；
  - Step 2: 【0秒动作接力】第 2 集及之后，开篇第 1 句动作行强制从 `previous_episode_0s_pickup` 姿态与道具无缝展开；全篇执行 Show Don't Tell（掐指/吞咽/倒吸冷气）；
  - Step 3: 对白前置括号写入发音物理状态与声带阻力，正文内显式嵌入三大声学标记；
  - Step 4: 正文末尾必须以【三位一体黄金悬念钩子 `golden_cliffhanger_hook`】收尾（物理危机动作+绝杀对白+声学下潜重击）；
  - Step 5: 结尾强制生成【集尾物理快照 `episode_end_physical_delta`】（封装时间线进度、身体姿态、道具伤势与环境天气），并自动接力注入下一集！
* **3. 生产与排异规则**：单次波次连续输出 3-4 集；单集输出标准 JSON 对象；彻底删除冗余配置字典与切碎数组；严禁发表人生感悟。
* **4. 输出数据契约 (必须包含顶格显式三大时空字段与纯文学正文)**：
```json
[
  {
    "episode_id": 2,
    "episode_title": "第 02 集：三万人的恩人，也是三万人的屠夫",
    "planned_duration_sec": 120.0,
    "dramatic_arc_unit": "单元 A (第 01 - 03 集) · 阶段 A 防御与伪装期",
    "core_dramatic_task": "林晚拒绝签字火化母亲遗体，在太平间外与周衍爆发关于生存与真相的初次对峙",
    "previous_episode_0s_pickup": {
      "inherited_from_episode": 1,
      "pickup_state_description": "林晚双膝半跪在旧公房厨房泥水里，右手手背撑地带发黑盐霜，左手将带血日记与药盒纸片死死按在胸口大衣内袋"
    },
    "screenplay_text": "【场景 01】外景/内景. 县城老火车站至县医院太平间 - 晨\n灰蒙蒙的雾气裹着刺鼻煤烟味。街头横幅猎猎作响：热烈祝贺周氏集团创立二十周年暨上市冲刺。\n承接上集终态，林晚从昨夜厨房泥水中站起换上黑色风衣，风衣下摆带着干结盐水泥斑，黑色旅行袋勒在肩头，快步走上太平间后门斜坡。\n桑塔纳警车怠速空转，排气管突突冒出白气。周衍倚在车门边，洗发白的警用夹克拉链敞着，左手拇指反复拨动磨砂银壳打火机。[声学行为: 开场突发重击 Braam Hit]...\n\n林晚\n（冷笑一声一把抽过确认书，指甲重重划过尸检图解，声音压得极平极稳）\n右后脑枕骨骨折，双脚跟腱没有任何垂直坠落挫伤。[声学行为: 核心戏剧骤停，进入主观绝对物理静音 3.0 秒]。\n她是被人后背朝下直接推下来的。\n\n周衍\n（猛地将纸扯回塞回大衣，胸口剧烈起伏，眼眶泛红低吼）\n你五年没回过县城，你连她住几楼都不知道！这是小县城，这里没有头条只有过日子！\n[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！",
    "golden_cliffhanger_hook": {
      "physical_crisis_action": "周衍粗暴扯回确认书死死塞回大衣，胸口剧烈起伏，两人在清晨浓雾碎石路上相隔三步撕破脸皮对峙",
      "cliffhanger_dialogue": "周衍眼眶泛红低吼：‘这是小县城，这里没有头条只有过日子！’",
      "acoustic_drop_cue": "[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
    },
    "episode_end_physical_delta": {
      "timeline_progress": "故事第 2 天上午 07:15，距离周氏集团上市答辩还剩 40 小时 45 分钟",
      "character_pose": "周衍大衣内兜塞着揉皱的确认书，后背抵在桑塔纳车门上粗重喘息；林晚站在两步开外，双手插在风衣口袋死死掐指",
      "held_props_and_injuries": "周衍右手紧握打火机，林晚旅行袋滑落垂在手腕，带血日记贴身在胸口大衣内袋，林晚右手拇指掐出指甲血痕",
      "environment_and_weather": "县医院太平间后门斜坡碎石路，冷雾弥漫，桑塔纳排气管白烟笼罩两人脚踝"
    },
    "audit_report": {
      "blue_team": "0秒接棒与上集终态完全对齐，前3秒Hook爆发力强，集尾黄金钩子声画标记完备",
      "red_team_critic": "周衍揉驼峰与眼神回避动作生动体现道德两难；林晚用尸检图解破局反转硬度极佳，无嘴替说白",
      "verdict": "GREEN_APPROVED"
    }
  }
]
```

---

### 【第二程：视听资产与分镜工程】

#### 阶段 6：分集增量视听资产提取与单项素材生成 (Incremental Asset Extraction & Generation)
* **1. 输入契约 (强制以阶段 5 文学剧本为唯一动态源头)**：
  - **核心动态输入**：必须强制读取并解析 **第一程阶段 5 输出的定稿文学剧本 `episodes_screenplay/ep_XX.json`**，具体提取：
    1. **`screenplay_text`** (影视级标准剧本正文：时空标头、视听动作行动词、发声呼吸括注、潜台词对白)；
    2. **`previous_episode_0s_pickup` 与 `episode_end_physical_delta`** (记录上一集肉体伤残、道具在谁身上、环境天气)；
  - **长期静态基准**：`01_bible.json` (画幅/风格) + `02_characters.json` (肖像DNA/服饰代码/声学腔体) + `05_visual_audio_assets.json` (全局总资产库)。
* **2. 内部思考协议 (CoT · 阶段 5 剧本多维特征逆向扫描识别引擎)**：
  大模型必须以 **阶段 5 的 `screenplay_text` 文本** 为唯一扫描靶心，严格运行三大扫描识别算子，严禁盲猜：
  - **【A. 角色资产识别与触发算子】**：
    1. *出场判定*: 逐行扫描 `screenplay_text` 中**每段对白前的独立行角色名（如“老郑”、“林晚”）**以及视听动作行中的人物专有名词 ➔ 提取本集实际出场人物清单；
    2. *四视角触发算子*:
       - 动作行命中 `["正面", "抬头", "直视", "走近", "迎面", "站立"]` ➔ 触发需要 `CHAR_<ID>_T1_4V_FRONT_FULL`；
       - 动作行命中 `["侧脸", "转头", "避开目光", "侧目", "向侧", "倚靠"]` ➔ 触发需要 `CHAR_<ID>_T2_4V_PROFILE`；
       - 动作行命中 `["斜视", "侧身", "3/4", "回眸", "半侧"]` ➔ 触发需要 `CHAR_<ID>_T2_4V_3Q`；
       - 动作行命中 `["背对", "背影", "转身离去", "后背", "远去"]` ➔ 触发需要 `CHAR_<ID>_T2_4V_BACK`；
    3. *情绪触发算子*: 扫描 `screenplay_text` 中角色对白前置括注（如 `（后槽牙死死咬紧，眼泪打转）`）中的发声状态与情绪动词 ➔ 触发生成 `CHAR_<ID>_T2_EXP_<EMOTION>`（仅生成剧本出现的情绪，无大笑绝不生大笑）；
    4. *光感触发算子*: 动作行命中 `["手电筒直射", "强光照脸", "闪光"]` ➔ 触发 `CHAR_<ID>_T2_LIGHT_FLASH`；动作行命中 `["阴暗", "侧逆光", "硬阴影", "月光", "烛光"]` ➔ 触发 `CHAR_<ID>_T2_LIGHT_LOWKEY`；
    5. *微距与伤残触发算子*: 动作行命中 `["手指", "掐掌心", "拉扯线头", "握住", "拿打火机"]` ➔ 触发 `CHAR_<ID>_T3_MACRO_HAND`；扫描 `previous_episode_0s_pickup` 或上集快照出现 `["淤青", "流血", "夹伤", "撕裂", "湿透"]` ➔ 强制触发 `CHAR_<ID>_T3_STATUS_<STATE>` 负伤/战损分支。
  - **【B. 场景资产识别与触发算子】**：
    1. *场景出场判定*: 扫描 `screenplay_text` 中每一个 `【场景 XX】` 或 `内景/外景` 时空标头 ➔ 提取独立场景；
    2. *景别与时态算子*:
       - 动作行第 1 句命中 `["远景", "全貌", "俯瞰", "大楼", "大门", "进站", "全景"]` ➔ 触发 `ENV_<ID>_T1_WIDE` (全景建立图)；
       - 场景内连续对白超过 3 句 ➔ 触发 `ENV_<ID>_T1_OTS_BG` (过肩景深板，自动背景虚化)；
       - 动作行命中 `["水龙头滴水", "挂钟秒针", "电表箱", "特写空镜"]` ➔ 触发 `ENV_<ID>_T1_INSERT_<PROP>`；
       - 时空标头时间变化 (如黄昏变深夜) 或动作行有火灾水淹 ➔ 触发增量注册 `ENV_<ID>_T1_STATE_<TIME>`；
       - 全剧仅出现 1-2 镜的次要场景 ➔ 仅触发 `ENV_<ID>_T2_KEYFRAME` (单张关键帧)。
  - **【C. 道具资产识别与触发算子】**：
    1. *道具出场判定*: 扫描 `screenplay_text` 视听动作行中被角色手部直接触碰、查看、操作的物理物件名词；
    2. *等级与形变算子*:
       - 扫描到一级核心物证 (血信/日记/安全帽) + 仅有 `["手持", "拿出", "查看", "抚摸", "按在胸口"]` ➔ 仅触发 `PROP_<ID>_T1_STATIC` (静态初始态)；
       - **扫描到一级核心物证 + 命中【形变破坏动词库】`["撕", "砸", "切", "断", "烧", "挑开", "崩碎", "撬开", "撞烂"]` ➔ 强制触发以静态图为底图局部重绘生成 `PROP_<ID>_T1_ACTION` (破坏交互态)！物件未被破坏绝不生两态**；
       - 扫描到角色随身物品 (打火机/戒指/手表/创可贴) ➔ 判定为二级锚定物，直接挂靠角色 `CHAR_<ID>_T3_MACRO_HAND`，零独立道具图；
       - 扫描到生活环境杂物 (冷水饺/茶杯/螺丝刀/碗筷) ➔ 判定为三级杂物，零独立生图，仅保留动作行文字描述。
  - **【D. 母音频实体化算子】**：新角色首次登场时，从 `screenplay_text` 中抓取该角色第 1 句高光对白金句（含发声括注），1:1 翻译阶段 2 腔体人设生成 `VOICE_<ID>_MASTER.wav`。
* **3. 生产与排异规则**：
  - 严禁一次性全量提取；已有 APPROVED 资产强制只读复用；三级杂物零独立图片；
  - 所有单项图强制继承 0 号基准肖像图并显式标注图生图底图 (`input_source_image`) 与重绘幅度 (`denoising_strength`)；
  - 每个新资产必须在 JSON 中显式输出 `script_inference_trigger` 字段，证明其触发的剧本动词依据。
* **4. 输出数据契约**：纯净标准 JSON，包含 `reused_existing_assets`、`newly_generated_assets`、`new_character_master_voice_cards` 与本集四分类 `episode_resource_manifest`，持久化合并写入 `05_visual_audio_assets.json`。

#### 阶段 7：逐集单镜头工业执行表生成与 SRT 导出 (Shot-by-Shot Storyboard & Contextual Voice)
* **1. 输入契约**：当前集剧本 `ep_XX.json` (`screenplay_text` + `previous_episode_0s_pickup` + `golden_cliffhanger_hook` + `episode_end_physical_delta`) + 阶段 6 本集资源引单 (`episode_resource_manifest`) + `05_visual_audio_assets.json` (仅 APPROVED 单项素材) + 阶段 5 任务卡 + 上一集时空总线快照 + 目标视频引擎 `target_engine` (默认为 `"wan3.0"`，可选 `"seedance2.5"`, `"minimax_h3"`)。
* **2. 内部思考协议 (CoT · 剧本视听转化与分镜识别算子引擎)**：
  大模型必须严格运行以下五大维度的【视听转化识别算子 (Script-to-Storyboard Translation Operators)】，严禁盲目凭感觉切镜头：
  - **【算子 1：景别与运镜识别算子 (Framing & Camera Operators)】**：
    * 动作行命中 `["手指", "刀尖", "信角", "蜡屑", "锁孔", "撕裂"]` ➔ 强制判定为 **【ECU 极微距】**，运镜锁定 `Slow Push-in (缓慢微推进)`；
    * 出现角色核心对白、面部神态、眼泪、咬牙 ➔ 强制判定为 **【MCU 中近景 / CU 特写】**，运镜锁定 `Static Gaze (静止冷峻凝视)`；
    * 本场为两人面对面对质且连续多句交锋 ➔ 强制判定为 **【OTS 过肩对峙镜头】**，运镜锁定 `Rack Focus (前后景变焦)`；
    * 场景标头切换第一句 + 命中 `["全貌", "大楼", "远景", "进站"]` ➔ 强制判定为 **【Wide 全景建立镜头】**，运镜锁定 `Slow Pull-back (微拉远)`。
  - **【算子 2：复合时序单镜整秒时长倒逼与自适应拆镜算子 (Sequential Duration & Adaptive Splitter)】**：
    * 复合时长计算公式: $T_{\text{total}} = T_{\text{前置动作/运镜}} + T_{\text{局部物证交互}} + \left( \frac{\text{台词字数}}{\text{语速 (3.0~3.5字/s)}} + 0.3\text{s (发声前吸气)} \right) + 0.4\text{s (句尾闭嘴缓冲)}$；
    * **整秒锁定与 7.0s 上限红线**:
      - 若 $T_{\text{total}} \le 6.5\text{s}$ ➔ **向上取整锁定绝对整秒 (`2.0s, 3.0s, 4.0s, 5.0s, 6.0s, 7.0s`)**，单镜头上限严格封顶为 **7.0s**；
      - **自适应拆镜决策树**: 若 $T_{\text{total}} > 6.5\text{s}$，严禁硬塞入单镜头，强制解耦拆分为前后咬合的双镜头：
        1. *镜头 A（铺垫动作镜，模式 A 或 B，2.0s~3.0s）*: 专心完成前置交互与视线推移，声音静音（台词为 `null`）；
        2. *镜头 B（核心对白特写镜，模式 B，4.0s~5.0s）*: 接续上一镜眼神，整句台词在此镜爆发，时间充裕，优雅闭环；
    * 台词入点与字幕咬合: 台词发声入点时间码 `speech_inpoint_sec` 精准顺延前置动作耗时，严禁半截话与字幕提前抢跑；
    * **全集累加与 $\pm$6.0s 弹性容差**: 全集所有镜头整秒累加值 $T_{\text{actual}} = \sum T_{\text{shot}}$ 与规划总时长 $T_{\text{plan}}$（如 120.0s）绝对误差必须 $\le \mathbf{6.0\text{s}}$（即落在 `[114.0s, 126.0s]` 弹性区间均合规放行，彻底消除为死凑 0 误差导致的虚假加减秒）；
    * **场景切片与流式装配流水线 (Scene Batching)**: 单集按剧本自然空间切分为 2~4 个批次吞吐（单批 7~10 镜，输出控制在 1,800~2,200 Tokens，杜绝输出截断），批次间传递 `batch_pickup_state` 绝对时间码与末镜头残局实现无缝咬合。
  - **【算子 3：生成模式与多模态提示词编译器 (Generation Mode & Multimodal Prompt Compiler)】**：
    * **IF (命中强物理形变/位移)**: 动作行命中【形变破坏动词库】`["撕", "砸", "切", "断", "烧", "挑开", "崩碎", "撬开"]` OR 包含门窗铁柜猛开、角色从站到摔倒 ➔ **强制判定为 `"first_last_frame"` (模式 A 首尾帧)**，出具首尾帧文生图 Prompt 与运动插帧 Prompt；
    * **ELSE (命中说话演技/微表情)**: 包含角色说话 (`audio.voice_type != null`) OR 面部微表情交锋 ➔ **强制判定为 `"multi_image_reference"` (模式 B 多模态参考)**，严格调用【模式 B 多模态提示词生成器规范】：
      1. *资产配置与独立编号 (先排后编)*: 依据当前分镜视觉焦点动态排序，填入 `media_manifest`。图片按内容焦点赋予「图1、图2...图N」（场景图严格唯一且出现 1 次，数组长 $\le 4$）；音频独立赋予「音频1、音频2...音频M」；严禁使用“场景图/人物图/道具图”等抽象指代；
      2. *关键约束前置*: 提示词开头第一句必须锚定空间关系（如：`图2站在图1的客厅中央，背对窗户，手中拿着图3。`）；
      3. *按叙事时序与单核心动作*: 动作按时间推进展开（站立 ➔ 动作 ➔ 微表情 ➔ 运镜 ➔ 台词）；单镜头仅保留 1 个核心动作；用具体动词替代抽象形容词；同一素材在不同动作节点可重复 @引用；
      4. *音频驱动极简化*: 音频是驱动源而非描述对象，**严禁在提示词中写语速、呼吸起伏、自然眨眼、口型同步指令**；情绪词仅保留 1 个（如“冷冽低沉”）；
      5. *目标引擎台词分支*:
         - `wan3.0`: 提示词不写台词原文，写为 `用[情绪词]说道（音频X）`；
         - `seedance2.5`: 写为 `用[情绪词]说道（音频X）："{台词原文}"`；
         - `minimax_h3`: 写为 `用[情绪词]说道（音频X）：(S1) [Chinese] "台词原文"`；
      6. *负向约束与 Token 瘦身*: 结尾附加 `无肢体畸变、无五官崩坏、无画面抖动。`；单镜内部审计精简为紧凑签名 `"audit": "PASS_9"`，完整的 9 项自检清单仅在集尾汇总出具一次。
  - **【算子 4：全息声音与发声阻力算子 (Holistic Acoustic Operator)】**：
    * 腔体与即时情绪识别: 括注命中咬牙/齿缝/发干 ➔ 编译至 `audio.contextual_tts_prompt`；
    * 拟音 Foley 识别: 扫描动词与材质 (如刀尖刮蜡 ➔ 编译 `+3.0dB 刀尖刮蜡划擦声`)，对齐动作发生秒数。
  - **【算子 5：口型动力学静默元数据算子 (LipSync Dynamics Metadata Operator)】**：
    * 下颌开度 `jaw_open_scale`: 咬牙/齿缝 `0.40 ~ 0.50`，大喊 `0.80 ~ 0.90`，常规 `0.60 ~ 0.65`；作为离线工具链静默元数据保留在 JSON 中，**绝对禁止写入视频提示词正文**。
* **3. 生产与排异规则**：
  - 所有分镜头必须为绝对整秒 (2s/3s/4s/5s/6s/7s)，全集秒数累加与规划总时长绝对误差 $\le 6.0\text{s}$；
  - 仅引用阶段 6 审核通过的 APPROVED 单项素材，严禁引用未裁切大图；
  - 模式 B 提示词必须 100% 遵循“先@后描述”、“按叙事时序”、“音频极简化”与 9 项自检标准；
  - 第 01 镜首帧 Prompt 强制绑定解析 `previous_episode_0s_pickup`；
  - 最后一镜尾帧与 TTS 强制绑定解析 `golden_cliffhanger_hook`；
  - SRT 字幕入点必须与台词发声时间码 `speech_inpoint_sec` 精准咬合，杜绝字幕提前抢跑；
  - 严禁单次整集全量硬吞输出，必须按场景批次生成后本地自动合龙。
* **4. 输出数据契约**：纯净机器可读分镜 JSON，写入 `storyboards/sb_XX.json`。

#### 阶段 8：多轨智能音频工程与成片混音调度 (Intelligent Audio Mastering & Mixing Engine)
* **1. 输入契约**：`01_bible.json` (风格/目标引擎) + `04_audio_bible.json` (动机母库) + 阶段 7 分镜 JSON 与 SRT 字幕 (实际总时长 $T_{\text{actual}}$ 与 `speech_inpoint_sec`) + 阶段 5 黄金钩子。
* **2. 内部思考协议 (CoT)**：
  - Step 1: 四大依据溯源（锁定母动机 A/B/C、动态读取阶段七实际累计总时长 $T_{\text{actual}}$（如 115s、124s，自适应 $\pm 6.0\text{s}$ 弹性区间，彻底废除写死 120s）、对白区间时间码与 `speech_inpoint_sec` 入点偏移、静音卡点）；
  - Step 2: 动态编译 Suno/Udio 全量 BGM Prompt（时长动态设置为 $T_{\text{actual}}$ 绝对秒数，片尾最后 2 秒 $[T_{\text{actual}} - 2.0\text{s}]$ 平滑淡出，片尾随黑屏硬切骤停，彻底杜绝视频黑屏后 BGM 多播拖音穿帮）；
  - Step 3: 精准分贝避让调度表（Mastering Schedule）：直接读取阶段七各镜头的 `speech_inpoint_sec` 入点偏移——在动作区间维持动作音量 `-12.0dB` 并精准卡入 `+3.0dB` 拟音；在 `speech_inpoint_sec` 开口之后才下沉触发对白避让 `-20.0dB`；第 45 秒断崖静音 3 秒；集尾 Sub-drop 骤停）；
  - Step 4: 出具 NLE 剪辑软件多轨导入指南。
* **3. 生产与排异规则**：人声响度锁定 -23 LUFS 标准；严禁拖音拖尾；调度表时间码与阶段七实际时间轴误差 0.0s。
* **4. 输出数据契约**：结构化音频工程 JSON，写入 `audio_mastering/ep_XX_audio_spec.json`。

---

## 六、 全阶段 1 至 8 字段级数据字典与契约规范 (Data Dictionary & Schemas)

### 1. 阶段 1 数据契约 (`01_bible.json`)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `slug` | `string` | 是 | 英文小写+下划线 | 项目唯一英文标识 (如 `seven_letters`)。 |
| `title` | `string` | 是 | 非空中文 | 本剧最终敲定的爆款官方剧名。 |
| `aspect_ratio` | `string` | 是 | `"vertical"` 或 `"horizontal"` | 发行画幅：竖屏 9:16 或 横屏 16:9。 |
| `duration_sec_per_ep` | `integer` | 是 | `90`, `120`, `150` | 单集规划物理基准总秒数。 |
| `target_episodes` | `integer` | 是 | `12`, `24`, `60` 等整数 | 全季规划总集数。 |
| `visual_style` | `string` | 是 | 风格标识 | 项目视觉风格定义 (如 `gritty_industrial_noir`)。 |
| `target_video_engine` | `string` | 是 (缺省 wan3.0) | `"wan3.0"`, `"seedance2.5"`, `"minimax_h3"` | 全剧目标视频生成引擎底模，缺省默认 `"wan3.0"`，向下直接贯穿并注入阶段七。 |
| `forbidden_cliches_10` | `array[string]` | 是 | 长度 $\ge 10$ 字符串数组 | 10 大绝对禁止老套因果清单（管因果逻辑）。 |
| `forbidden_cheap_tropes_3`| `array[string]` | 是 | 长度 $\ge 3$ 字符串数组 | 3 大绝对禁止廉价爽点清单（管情绪格调）。 |
| `logline` | `string` | 是 | 符合工业公式长句 | 一句话核心故事梗概（危机+缺陷+阻碍+倒计时+代价）。 |
| `core_irony` | `string` | 是 | 戏剧讽刺长句 | 主角追求目标与现实结果的深层悲剧/讽刺内核。 |
| `grand_payoff` | `string` | 是 | 终局核爆长句 | 全季最后一集必须物理引爆的大结局核心事件。 |

### 2. 阶段 2 数据契约 (`02_characters.json`)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `characters[].character_id` | `string` | 是 | `CHAR_<NAME>` | 角色唯一英文标识 (如 `CHAR_LINWAN`, `CHAR_LUCHEN`)。 |
| `characters[].name` | `string` | 是 | 角色中文名 | 角色正式中文姓名 (如 `林晚`, `陆沉`)。 |
| `characters[].gender` | `string` | 是 | `"male"` 或 `"female"` | **生理性别（强制必填，杜绝性别幻觉与配音错乱）**。 |
| `characters[].perceived_age` | `integer` | 是 | 整数年龄 (如 `28`, `38`) | 视觉与声学生理感知年龄，严禁带“岁”或文字。 |
| `characters[].role_type` | `string` | 是 | `"protagonist"`, `"antagonist"`, `"supporter"` | 角色戏剧定位：核心主角、宿命对手/反派、关键纽带配角。 |
| `characters[].personality` | `string` | 是 | 性格特征长句 | 角色核心性格特质、处事风格与行为防线。 |
| `characters[].appearance` | `string` | 是 | 中景视觉概括长句 | 角色整体第一视觉印象与体态概括（严禁混入微观骨相与抽象心理）。 |
| `characters[].identity_anchors` | `array[string]` | 是 | 3~5 个具象短语列表 | **生图锁脸与锁特征 Prompt 标签** (如 `["高颧骨鹰隼眼", "深灰粗花呢大衣", "额角浅旧伤", "随身旧物"]`)。 |
| `characters[].voice_style` | `string` | 是 | 通俗声音风格长句 | 角色通俗声音风格概述 (如 `低沉沙哑，胸腔共鸣明显，语速克制偏慢`)。 |
| `characters[].acoustic_persona` | `object` | 是 | 声学人设物理对象 | 包含 `vocal_position` (发声发力腔体位置), `vocal_flaws` (声带疲劳发干 Vocal Fry 比例约30%/齿擦音), `speed_and_intonation` (语速系数0.88~0.92与句尾果断平收调)。 |
| `characters[].biological_dna` | `object` | 是 | 微观生物骨相 DNA 对象 | 包含 `face_shape` (骨骼折叠度与下颌角), `skin_pores` (真实毛孔与粗糙度), `permanent_flaws_coordinates` (**毫米级痣/疤痕具体坐标与尺寸**), `eyes_and_lips` (内双眼褶深度/血丝/嘴唇皲裂咬痕), `hair_texture` (发质发型/雨水打湿碎发)。 |
| `characters[].lived_in_costume` | `object` | 是 | 真实生活质感服化道对象 | 包含 `outerwear_fabric_wear` (**面料材质克重 g/m²、自然折痕、松脱线头长度 cm、下摆泥斑**), `innerwear` (领口起球与汗渍硬壳感), `bottoms_and_shoes` (水磨白印/鞋跟磨偏 3mm), `anchor_props` (随身不可变固有饰品/金属扣氧化绿锈)。 |
| `characters[].psychology_4` | `object` | 是 | 心理动力学四元组对象 | 包含 `want` (表层欲望与直接目标), `need` (深层内在成长救赎), `the_lie` (深信不疑的致命防御谎言), `the_ghost` (过去不可挽回的创伤原罪)。 |
| `characters[].voice_fingerprint` | `object` | 是 | 语言指纹与应激微动作对象 | 包含 `catchphrase` (标志性口头禅), `defensive_phrase` (被刺痛时的防御反击语), `forbidden_words` (绝对心理禁词列表), `stress_action` (焦虑应激生理动作，如用力掐食指指甲缝/咬下唇内侧)。 |
| `characters[].carried_anchor_item` | `object` | 是 | 随身核心信物/物理锚定物 | 包含 `item_name` (信物名称), `physical_trace` (精确物理磨损刻痕/氧化做旧/机械卡涩), `emotional_significance` (背后的深层前史秘密与创伤信物意义)。 |
| `relationship_matrix` | `array[object]` | 是 | 双轨关系网络矩阵 | 包含 `character_a`, `character_b`, `surface_relation` (表面社会身份), `emotional_bond` (深层情感羁绊), `fatal_interest_conflict` (**不可调和的生死利益死结**), `shared_history_props` (承载共同生活前史的旧情密码物证)。 |
| `emotional_arc_trajectory` | `object` | 是 | 全季四阶段情感流转弧 | 包含 `stage_a_guarded` (0-25% 谎言防御期), `stage_b_fracture` (25-50% 信念崩解期), `stage_c_abyss` (50-75% 灵魂深渊自剖期), `stage_d_catharsis` (75-100% 终极救赎和解期)。 |

### 3. 阶段 3 数据契约 (`03_environments_props.json`)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `environments[].env_id` | `string` | 是 | `ENV_<NAME>` | 场景唯一标识 (如 `ENV_MOTHER_APARTMENT`)。 |
| `environments[].level` | `string` | 是 | `"primary_tier1"` 或 `"transitional_tier2"` | 场景分级：一级核心主场景 ($\ge 3$场戏) 或 二级过渡次场景 (1-2镜)。 |
| `environments[].three_layer_aging` | `object` | 是 | 三层做旧对象 | 包含 `structure` (建筑年代管线), `lived_grime` (水渍/发黑霉斑/划痕), `light_and_air` (微尘/冷暖色温)。 |
| `environments[].costume_resonance_check`| `boolean` | 是 | 强制为 `true` | 确认场景脏旧度与角色服装磨损度 100% 同频共振。 |
| `props[].prop_id` | `string` | 是 | `PROP_<NAME>` | 道具唯一标识 (如 `PROP_BLOOD_LETTER`)。 |
| `props[].level` | `string` | 是 | `"hero_tier1"`, `"anchor_tier2"`, `"atmospheric_tier3"` | 道具分级：一级核心物证 (支持双态)、二级角色锚定物 (并入手部)、三级环境杂物 (零生图)。 |
| `props[].physical_specs` | `object / null`| 一级物证必填 | 物理阻力与拟音对象 | 包含 `material_damage_dimensions` (破损尺寸/渗墨毛刺), `weight_and_haptic_resistance` (质量与阻力感), `foley_boost_db` (`"+3.0dB"` 拟音指令)。 |

### 4. 阶段 4 数据契约 (`04_outline.json` & `04_audio_bible.json`)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `leitmotif_registry` | `array[object]` | 是 | 长度 = 3 的动机数组 | 全剧核心音乐动机母库：包含 `leitmotif_id`、配器列表 (`prepared_piano`, `solo_cello` 等)、BPM、调性、情感戏剧功能。 |
| `mini_arc_units` | `array[object]` | 是 | 3-4 集/单元数组 | 划分全季小高潮单元 (如 `单元 A: 第 01 - 03 集 · 开局死局与血信破壁`)。 |
| `episodes[].episode_id` | `integer` | 是 | $\ge 1$ 整数 | 剧集序号。 |
| `episodes[].killer_title` | `string` | 是 | 爆款吸睛标题 | 强悬念、反常识、冲突前置的单集标题。 |
| `episodes[].dual_helix_task` | `object` | 是 | 双螺旋任务卡对象 | 包含 `plot_event_chain` (外部事件链), `relational_shift_point` (**核心人物关系不可逆质变点**), `lie_erosion_metric` (**主角致命谎言崩解度**)。 |
| `episodes[].hook_3s` | `string` | 是 | 具象物理动作 | 前 3 秒必须爆发的极端物理异动（动作与物件）。 |
| `episodes[].micro_twist_45s` | `string` | 是 | 微观因果破局点 | 第 40-60 秒基于角色生理伤痕或服饰破绽推翻假定的具体破局事件。 |
| `episodes[].cliffhanger_end` | `string` | 是 | 实打实物理危机 | 集尾动作最高潮的生死/利益绝杀断点（严禁做梦与误会式虚空诈骗）。 |

### 5. 阶段 5 数据契约 (`episodes_screenplay/ep_XX.json` 显式时空总线字典)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `episode_id` | `integer` | 是 | $\ge 1$ 整数 | 当前单集的物理序号 (如 1, 2, 3...)。 |
| `episode_title` | `string` | 是 | 非空中文 | 阶段 4 锁定的本集爆款吸睛悬念标题。 |
| `planned_duration_sec` | `number` | 是 | 浮点数 (如 `120.0`) | 本集规划总时长，必须严格对齐阶段 1 基本盘。 |
| `dramatic_arc_unit` | `string` | 是 | 非空字符串 | 标明本集所属的全季戏剧单元与情感阶段。 |
| `core_dramatic_task` | `string` | 是 | 非空字符串 | 本集核心戏剧任务（来自阶段 4 工笔任务卡）。 |
| `previous_episode_0s_pickup` | `object / null` | 是 | 对象或 `null` | **【0 秒接棒快照】**：第 1 集为 `null`；第 2 集及之后必须为对象，包含 `inherited_from_episode` 与 `pickup_state_description`，作为开篇第 1 行动作行物理起点。 |
| `screenplay_text` | `string` | 是 | 纯文本带 `\n` | **核心文学原件全文**！包含标准场景标头【场景 XX】、纯动词动作行 Show Don't Tell、发声呼吸括注、潜台词对白与三大声学行为标记。 |
| `golden_cliffhanger_hook` | `object` | 是 | 结构化对象 | **【结尾黄金悬念钩子】**：包含 `physical_crisis_action` (实打实物理危机动作), `cliffhanger_dialogue` (绝杀台词), `acoustic_drop_cue` (声学骤停标记)。 |
| `episode_end_physical_delta` | `object` | 是 | 结构化对象 | **【集尾物理状态快照】**：完整封装最后一秒残局供下集接棒，包含 `timeline_progress` (时间线倒计时), `character_pose` (绝对姿态), `held_props_and_injuries` (手持道具与伤势), `environment_and_weather` (天气空间)。 |
| `audit_report` | `object` | 是 | 结构化自审对象 | 包含 `blue_team` (合规结论), `red_team_critic` (刺痛挑刺), `verdict` (`"GREEN_APPROVED"` 或 `"RED_BLOCKED"`)。 |

### 6. 阶段 6 数据契约 (`05_visual_audio_assets.json` 全字段叶子节点穷尽展开字典)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `episode_id` | `integer` | 是 | $\ge 1$ 整数 | 当前单集的物理序号。 |
| `episode_title` | `string` | 是 | 非空中文 | 阶段 4 锁定的本集爆款吸睛悬念标题。 |
| `global_assets_summary` | `object` | 是 | 统计对象 | 包含 `total_registered_characters` (收录总人数), `total_registered_environments` (总场景数), `total_registered_props` (总道具数)。 |
| `reused_existing_assets[].asset_id` | `string` | 存在则填 | 已注册资产 ID | 本集直接复用的老资产 ID (如 `CHAR_LIN_BASE_PORTRAIT`)，强制只读继承。 |
| `reused_existing_assets[].type` | `string` | 存在则填 | 资产类别标识 | 如 `character_base_identity`, `environment_keyframe`。 |
| `reused_existing_assets[].usage_in_current_ep` | `string` | 存在则填 | 文本说明 | 声明该老资产在本集中的具体用途（如“本集所有林晚镜头的人脸身份参考源”）。 |
| `reused_existing_assets[].status` | `string` | 存在则填 | 固定值 `"APPROVED"` | 必须为已批准状态。 |
| `newly_generated_assets[].asset_id` | `string` | 新增必填 | 四段式资产 ID | 本集新生成的单项资产 ID (如 `CHAR_LIN_4V_FRONT_FULL`, `PROP_01_ACTION`)。 |
| `newly_generated_assets[].asset_category` | `string` | 新增必填 | 资产分级枚举 | `character_tier1_base`, `character_tier2_performance`, `character_tier3_special`, `env_tier1_primary`, `env_tier2_transitional`, `prop_tier1_hero` 等。 |
| `newly_generated_assets[].script_inference_trigger` | `string` | 新增必填 | 剧本动词依据长句 | **剧本逆向推理铁证**！写明是扫描到当前集哪一场哪一行动作行（如“美工刀挑开蜂蜡”形变动词）而触发生成的。 |
| `newly_generated_assets[].generation_method` | `string` | 新增必填 | 枚举值 (Enum) | `"text_to_image"` (纯文生图), `"image_to_image_outpainting"` (画面扩展), `"image_to_image_pose"` (姿态旋转), `"inpainting_local_edit"` (局部重绘), `"relighting"` (重光照)。 |
| `newly_generated_assets[].input_source_image` | `string / null` | 新增必填 | 输入底图资产 ID 或 `null` | **图生图底图来源** (如 `CHAR_LIN_BASE_PORTRAIT`, `PROP_01_STATIC`)，纯文生图填 `null`。 |
| `newly_generated_assets[].identity_reference` | `string / null` | 角色图必填 | 角色基准肖像 ID | 角色所有图生图必须指向 `CHAR_<ID>_BASE_PORTRAIT` 锁死身份，非角色图为 `null`。 |
| `newly_generated_assets[].denoising_strength` | `number / null` | I2I必填 | `0.30 ~ 0.60` 浮点数 | 图生图重绘幅度：四视图 `0.45`，微表情 `0.40`，光感 `0.35`，微距 `0.50`。 |
| `newly_generated_assets[].aspect_ratio` | `string` | 新增必填 | `"4:5"`, `"1:1"`, `"9:16"` 等 | 本单项素材的专用画幅比例。 |
| `newly_generated_assets[].image_prompt` | `string` | 新增必填 | 完整英文生图 Prompt | 包含风格介质、生物骨相/做旧面料/微距参数，带 `--style raw`。 |
| `newly_generated_assets[].status` | `string` | 新增必填 | 固定值 `"APPROVED"` | 新生成并通过审核的资产状态。 |
| `new_character_master_voice_cards[].character_id` | `string` | 新角色必填 | 角色唯一 ID | 如 `CHAR_LINWAN`。 |
| `new_character_master_voice_cards[].master_voice_id` | `string` | 新角色必填 | `VOICE_<NAME>_MASTER` | 母音频唯一标识 (如 `VOICE_LINWAN_MASTER`)。 |
| `new_character_master_voice_cards[].script_monologue_source` | `string` | 新角色必填 | 剧本高光台词带括注 | 从已定稿文学剧本抓取的灵魂示范台词（包含发声括注与微观停顿）。 |
| `new_character_master_voice_cards[].master_tts_prompt` | `string` | 新角色必填 | 全量英文 TTS Prompt | 1:1 翻译阶段 2 腔体人设、声带发干 Vocal Fry 与语速基频的生音提示词。 |
| `new_character_master_voice_cards[].voice_file_path` | `string` | 新角色必填 | 标准音频路径 | `audio_mastering/voices/VOICE_[ID]_MASTER.wav`。 |
| `episode_resource_manifest.characters.tier1_base[]` | `array[object]` | 是 | 一级角色基础列表 | 包含 `character_id`, `base_portrait`, `base_costume`, `master_voice`。 |
| `episode_resource_manifest.characters.tier2_performance[]` | `array[object]` | 是 | 二级角色表现列表 | 包含 `character_id`, `angle_views` (角度数组), `script_emotions` (剧本情绪数组)。 |
| `episode_resource_manifest.characters.tier3_special[]` | `array[object]` | 是 | 三级角色专项列表 | 包含 `character_id`, `special_macro` (手部/眼唇微距), `status_branch` (负伤/战损分支)。 |
| `episode_resource_manifest.environments.tier1_primary[]` | `array[object]` | 是 | 一级主场景列表 | 包含 `env_id`, `wide_shot`, `insert_shot`, `lighting_state`。 |
| `episode_resource_manifest.environments.tier2_transitional[]` | `array[object]` | 是 | 二级次场景列表 | 包含 `env_id`, `keyframe_asset` (单张关键帧)。 |
| `episode_resource_manifest.props.tier1_hero[]` | `array[object]` | 是 | 一级核心物证列表 | 包含 `prop_id`, `static_asset`, `action_asset` (破坏态), `haptic_resistance` (物理阻力与+3dB拟音)。 |
| `episode_resource_manifest.props.tier2_anchor[]` | `array[object]` | 是 | 二级锚定道具列表 | 包含 `prop_id`, `attached_character_macro` (挂靠的角色手部微距)。 |
| `episode_resource_manifest.props.tier3_atmospheric[]` | `array[object]` | 是 | 三级环境杂物列表 | 包含 `item_name`, `scene`, `motion_note` (纯动词交互，零图片生成)。 |
| `episode_resource_manifest.audio.voices_used[]` | `array[string]` | 是 | 字符串数组 | 本集涉及的所有母音频 ID 列表 (如 `["VOICE_LINWAN_MASTER"]`)。 |
| `episode_resource_manifest.audio.foley_focus` | `string` | 是 | 拟音重点文本 | 标明本集必须放大的微观拟音 (如 `"+3dB 刀尖刮蜡划擦声"` )。 |
| `audit_report.blue_team` | `string` | 是 | 蓝军合规结论 | 确认角色三级、场景两级、道具三级分类与图生图参数完备。 |
| `audit_report.red_team_critic` | `string` | 是 | 红军刺痛挑刺 | 针对四视图全身完整性、道具形变底色继承、AI 假人感进行严格把关。 |
| `audit_report.verdict` | `string` | 是 | `"GREEN_APPROVED"` / `"RED_BLOCKED"` | 阶段 6 最终审核放行结论。 |

### 7. 阶段 7 数据契约 (`storyboards/sb_XX.json`)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `shots[].shot_id` | `integer` | 是 | 递增整数 (1, 2...) | 镜头序号。 |
| `shots[].duration_sec` | `number` | 是 | **必须为整数秒** (`2.0`, `3.0`, `4.0`, `5.0`, `6.0`, `7.0`) | 单镜头绝对整数秒（上限 7.0s）；全集秒数累加与规划时长（如 120.0s）绝对误差 $\le 6.0\text{s}$（114.0s~126.0s 放行）。 |
| `shots[].timecode` | `string` | 是 | `HH:MM:SS,mmm --> HH:MM:SS,mmm` | 镜头起止绝对时间码，毫秒部分必须与整秒对齐。 |
| `shots[].rationale` | `string` | 是 | 非空字符串 | **算子 1+2 决策依据**：景别依据与复合时长累加推导（如 `MCU推至CU(2s)+台词(4s)+缓冲(0.4s) 向上取整锁死 7s`）。 |
| `shots[].generation_mode` | `string` | 是 | 枚举值: `"first_last_frame"` 或 `"multi_image_reference"` | 生成模式二选一：强物理形变破坏选前者，对白微表情选后者。 |
| `shots[].selection_rationale` | `string` | 是 | 非空字符串 | **算子 3 模式选型依据**：写明命中形变动词库或核心对白演技库的判定理由。 |
| `shots[].target_engine` | `string` | 模式B必填 | `"wan3.0"`, `"seedance2.5"`, `"minimax_h3"` | 模式 B 目标多模态视频生成模型引擎标识。 |
| `shots[].first_last_frame_config` | `object / null` | 模式A必填 | 包含首尾帧Prompt对象 | 模式 A 必须包含 `first_frame_asset_ref`, `first_frame_prompt`, `last_frame_asset_ref`, `last_frame_prompt`, `video_motion_prompt`；模式 B 强制为 `null`。 |
| `shots[].multi_image_config.media_manifest` | `object` | 模式B必填 | 结构化符号映射表 | 包含 `images` 数组 (`symbol: "图1"`, `asset_id`, `role`) 与 `audios` 数组 (`symbol: "音频1"`, `voice_id`, `role`)，图音独立计数。 |
| `shots[].multi_image_config.reference_assets`| `array[string]` | 模式B必填 | 四段式资产 ID 数组 | 按当前分镜视觉焦点动态排序后的资产数组（首位为第一焦点，场景唯一，长度 $\le 4$）。 |
| `shots[].multi_image_config.video_prompt` | `string` | 模式B必填 | 终极原生视频提示词 | 先@后描述、按叙事时序、单核心动作、音频极简不写口型/眨眼、符合目标模型台词规范、带负向约束。 |
| `shots[].multi_image_config.audit` | `string` | 模式B必填 | 固定值 `"PASS_9"` | 单镜轻量化紧凑签名（9 项自检在后台 100% 闭环，集尾统一汇总出具报告）。 |
| `shots[].audio.speech_inpoint_sec` | `number / null` | 说话戏必填 | 浮点秒数 (如 `2.5`) | 台词发声相对于镜头起点的入点偏移秒数，对齐提示词动作时序。 |
| `shots[].audio.is_dialogue_complete_in_shot` | `boolean` | 是 | `true` 或 `false` | 标明本句台词在该镜头内是否 100% 语义完整说完（强制为 `true`，严禁半截话）。 |
| `shots[].audio.contextual_tts_prompt` | `string / null` | 说话戏必填 | 包含 Voice ID、即时情绪与断句脚本 | 动态编译的全息 TTS 提示词，供阶段 8 混音或独立生音。 |
| `shots[].lipsync_dynamics.jaw_open_scale` | `number / null` | 说话戏必填 | `0.0 ~ 1.0` 浮点数 | 离线静默元数据（严禁写入 video_prompt，保留给离线口型工具备用）。 |
| `srt_export` | `string` | 是 | 标准 SRT 纯文本带 `\n` | 依据台词入点偏移与分镜绝对时间码导出的毫秒级标准字幕纯文本。 |
| `audit_report.mode_b_manifest_check` | `object` | 模式B必填 | 集尾全量 9 项自检大审字典 | 全集所有模式 B 镜头 9 项合规指标汇总核验结果（必须全部为 `true`）。 |

### 8. 阶段 8 数据契约 (`audio_mastering/ep_XX_audio_spec.json`)
| 字段路径 (JSON Key) | 类型 (Type) | 必填 | 允许值/格式约束 | 字段物理语义与生成规则 |
|---|---|---|---|---|
| `audio_specs.broadcast_loudness_standard` | `string` | 是 | 固定值 `"-23 LUFS"` | 国际通用影视广播级响度标准。 |
| `acoustic_traceability` | `object` | 是 | 四大依据溯源对象 | 包含 `stage_4_leitmotif_basis`, `stage_1_worldview_basis`, `stage_7_timecode_basis`, `stage_5_dramatic_cues`。 |
| `bgm_generation.full_master_prompt` | `string` | 是 | 完整生乐英文 Prompt | 包含风格、时长、BPM 速度、配器、分段秒数标记与混音词，直接粘贴至 Suno/Udio。 |
| `mastering_schedule[].target_bgm_volume_db` | `number` | 是 | 浮点分贝值 (dB) | BGM 目标音量：对白区 `-20.0`，动作区 `-12.0`，**断崖静音强制填 `-999.0` (代表 -∞ dB)**。 |
| `mastering_schedule[].speech_ducking_active` | `boolean` | 是 | `true` 或 `false` | 是否在该区间激活语音侧链自动避让。 |
| `nle_mixing_guidelines` | `object` | 是 | 4 轨参数规范字典 | A1 对白轨、A2 拟音轨、A3 BGM 轨、V1/V2 视频字幕轨的导入参数指南。 |

---

## 七、 多模态 AI 制作工具链落地操作闭环

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 【阶段 7 JSON 交付】 ➔ 【阶段 8 JSON 交付】                                │
│                                                                             │
│  [动作 1: 画面生成]                                                         │
│    - 若 `first_last_frame`: 将首尾帧 Prompt 喂给可灵/Runway 生成物理动作；   │
│    - 若 `multi_image`: 将 media_manifest 素材与 video_prompt 喂给 Wan3.0 / Seedance 2.5 / MiniMax H3 渲染成片；│
│                                                                             │
│  [动作 2: 配音生成]                                                         │
│    - 将 `contextual_tts_prompt` 粘贴进 CosyVoice / ElevenLabs，生成对白音频；│
│    - 导入 LivePortrait / Hedra 执行口型同步 (对齐 jaw_open_scale 参数)。     │
│                                                                             │
│  [动作 3: 音乐生成]                                                         │
│    - 将阶段 8 的 `full_master_prompt` 粘贴进 Suno v3.5 生成与分镜实际总时长一致的定制 BGM。│
│                                                                             │
│  [动作 4: 剪辑总装 (剪映 / Premiere / CapCut)]                              │
│    - 导入视频切片至 V1，导入 `srt_export` 文本至 V2；                        │
│    - 导入对白音频至 A1 (设为 0dB)，导入拟音至 A2 (增益 +3dB)；               │
│    - 导入 BGM 至 A3，开启 Audio Ducking (衰减 -14dB)；                       │
│    - 照着 `mastering_schedule` 在第 45 秒做 3 秒断崖静音；在集尾最后 2 秒平滑淡出。│
│                                                                             │
│  ➔ 导出即是符合广播级响度、毫秒级音画咬合的【最终短剧发行级视频成片】！    │
└─────────────────────────────────────────────────────────────────────────────┘
```