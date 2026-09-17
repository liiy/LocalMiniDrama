---
name: screenplay-pipeline
description: 通用AI原创连续剧短剧工业化生产管线。当用户想要创作、生成、编写短剧、剧本、分镜或分集大纲时触发（例如：写短剧, 剧本创作, AI短剧, 生成分镜, 连续剧剧本, 短剧大纲, 短剧人物设定, 短剧立项）。采用两程九阶工业架构（第一程全季文学剧本逐集定稿闭环 ➔ 第二程多模态视听基准资产提取 ➔ 逐集单镜头首尾帧与多图参考分镜生成，带资源引单与TTS绑定）。
version: 5.4.0
---
# AI 原创连续剧短剧工业管线标准作业程序 (AI Serial Micro-Drama Master SOP v5.4.0 - 终极工业全息闭环版)

本系统专为 AI 原创短剧打造，完全适配短剧算法逻辑。
全管线采用**“两程九阶（Two-Journey, Nine-Stage）”**工业流转体系：
* **第一程【文学故事工程】**：从题材破壁一直到**逐集完成全季所有原剧文学剧本定稿**，确保全季伏笔闭环与戏剧情绪连贯；
* **第二程【视听资产与分镜工程】**：文学定稿后，先集中提炼角色/道具/场景的多视图与高清生图 Prompt 矩阵，再逐集输出支持**首尾帧生视频（First-Last-Frame）**与**多图参考生视频（Multi-Image I2V）**的标准分镜头执行表，并在每集分镜前置输出**本集视听资源引单 (Episode Resource Manifest)**，为台词与旁白配置精确的 AI TTS 声学指令。

---

## 一、 双程工业架构流转全景图 (Dual-Journey Architecture)

```
====================================================================================================
【第一程：文学故事工程 (The Literary Journey)】—— 编剧室闭环，全季故事逻辑与伏笔锁死
====================================================================================================
[阶段 1: 题材破壁与创意引擎] ──► 产出: 01_bible.json (双轨禁令母集 / 爆款候选片名矩阵 / 工业Logline / 终局核爆点)
          │
          ▼
[阶段 2: 角色全息人设、肖像DNA、生活质感服饰与关系网建模] ──► 产出: 02_characters.json (生物肖像骨相DNA / 真实生活质感服饰代码 / 心理四元组 / 语言行为指纹 / 四阶段情感弧 / 双轨关系矩阵)
          │
          ▼
[阶段 3: 空间设计与物证规划] ──► 产出: 03_environments_props.json (场景三层做旧架构 / 核心反转物证功能与隐喻)
          │
          ▼
[阶段 4: 全季爆款分集大纲规划] ─► 产出: 04_outline.json (全季季钩 / 各集吸睛悬念标题 / Hook / 微反转 / 断点)
          │
          ▼
[阶段 5: 疾速波次连续吞吐 · 全季文学剧本产出 (Turbo Mini-Arc Batching)] 
          │ ──► 按 3-4 集戏剧小高潮单元连续输出并落盘: episodes_screenplay/ep_01.json ~ ep_NN.json
          │     (单次交付一个完整情绪波浪，集间 0 秒物理自动接力，末尾合并红蓝挑刺总检)
          ▼
   🛑【第一程全季文学定稿门控】(全季 12-24 集仅需 3-6 次交互即可全季文学定稿，指令放行进入第二程)

====================================================================================================
【第二程：视听资产与分镜工程 (The Visual & Storyboard Journey)】—— 单集微循环流水线 (Episode Loop)
====================================================================================================
(第一程全季文学原件 episodes_screenplay/ep_01.json ~ ep_NN.json 已全量定稿，第二程逐集滚动闭环：)

 ┌──►【单集循环起点：第 XX 集启动】(读取当前集文学稿 ep_XX.json 与上集物理快照)
 │        │
 │        ▼
 │   [阶段 6: 第 XX 集按需资产准备] (查库复用老资产，按需增量生成新资产/状态分支，输出本集资源引单)
 │        │
 │        ▼ 🛑【阶段 6 单集资产审查门控】(放行后进入阶段 7)
 │        │
 │   [阶段 7: 第 XX 集分镜头工业执行表与 SRT 导出] (单镜 2.5-4.5s，全息声画咬合，导出 ep_XX.srt)
 │        │
 │        ▼ 🛑【阶段 7 单集分镜与SRT审查门控】(放行后进入阶段 8)
 │        │
 │   [阶段 8: 第 XX 集多轨智能音频工程与混音调度] (定制BGM Prompt、动态分贝避让表、剪辑轨道指南)
 │        │
 │        ▼ 🛑【阶段 8 单集结项审查门控】
 │        │
 └────────┴──► 若 XX < 全季总集数：提取【集尾物理快照】，自动步入【第 XX+1 集阶段 6】！
               若 XX == 全季总集数：全季第二程正式圆满收官，交付全套工程资产！
```

---

## 二、 阶段间长短期记忆输入/输出契约矩阵 (Memory I/O Matrix)

| 阶段 | 读取的【全局长期记忆】 | 读取的【流动短期记忆】 | 产出的【本阶段长期资产】 | 产出的【下传短期记忆便签】 |
| :--- | :--- | :--- | :--- | :--- |
| **阶段 1：题材破壁** | 用户输入参数 | 无（管线初始启动） | `01_bible.json`<br>- 画幅、单集时长、风格<br>- 负向双轨禁令清单母集<br>- 爆款片名矩阵、Logline、终局核爆点 | **【短期记忆 A：人设禁令子集 + 核心讽刺】**<br>提炼主角致命缺陷及防伟光正/防龙傲天指令。 |
| **阶段 2：角色全息人设与关系网建模** | `01_bible.json` (画幅/风格/禁令) | **【短期记忆 A：人设禁令子集 + 核心讽刺】** | `02_characters.json`<br>- **微观生物肖像与骨相 DNA (毫米级瑕疵)**<br>- **从头到脚真实生活质感服饰代码 (Lived-in)**<br>- 心理四元组、语言行为指纹<br>- 全季四阶段动态情感流转图<br>- 利益与情感双轨关系矩阵 | **【短期记忆 B：肖像骨相DNA + 真实服饰代码 + 关系死结网】**<br>作为阶段 5 动作发音描写与阶段 6 生图编译的绝对基准。 |
| **阶段 3：空间与道具规划** | `01_bible.json`<br>`02_characters.json` | **【短期记忆 B】** | `03_environments_props.json`<br>- 核心场景三层做旧规划<br>- 核心物证叙事隐喻与破损形态规划 | **【短期记忆 C：大纲冲突要素包】**<br>提炼推动剧情大反转的核心场景与道具。 |
| **阶段 4：双螺旋分集大纲规划** | `01`核爆点/双轨禁令<br>`02`全剧情感弧与关系网<br>`03`核心物证 | **【短期记忆 C】** | `04_outline.json`<br>- 全季各集爆款悬念标题<br>- **双螺旋：外部事件 + 单集核心关系质变点**<br>- **主角当集心理谎言崩解度 (Lie Erosion)**<br>- 全剧核心音乐动机母库 | **【短期记忆 D：工笔级双螺旋剧作路线图】**<br>包含外部事件链与人物关系质变切片。 |
| **阶段 5：全季文学剧本疾速波次产出** | `01`双轨禁令母集<br>`02`角色语言指纹<br>`03`场景物证隐喻<br>`04`工笔级任务卡与断点 | **【单元内自动接力短期记忆：集间物理快照】** (批次内无缝咬合) | `episodes_screenplay/`<br>`ep_01.json ~ ep_NN.json`<br>- 结构化纯文学剧本 JSON 数组（3-4集/波次，含护栏锁/动作行/发声括注/自审） | **【第一程终结：全季故事逻辑与伏笔闭环快照】**<br>全季文学正式定稿。 |
| **阶段 6：多模态视听基准资产分集增量提取** | **汇聚阶段 1-5 所有文学与人设档案** + `05_visual_audio_assets.json` (真理源总库) | **【当前集文学剧本 JSON】** | `05_visual_audio_assets.json`<br>- 角色分级资产与需求扫描结果<br>- 身份基准图、按需四视图/表情/光感/服饰/微距/状态图<br>- 场景、道具、TTS 单项资产与状态分支<br>- 资产来源、版本、用途与 APPROVED/REJECTED 状态 | **【第二程基石：第 XX 集视听资产切片引单】**<br>为后续单镜头分镜提供精准切片与声音引用索引。 |
| **阶段 7：逐集分镜头工业执行表** | `01`画幅参数与时长<br>`05`视听基准资产总库（仅引用APPROVED单项素材）<br>`episodes_screenplay/ep_XX.json` | 1. **【当前集文学剧本 JSON】**<br>2. **【上一集分镜最后一秒物理快照】** (姿态/手持道具/空间) | `storyboards/sb_01.json ~ sb_NN.json`<br>- 单集纯净机器可读 JSON 数据契约<br>- 双模式首尾帧/多图精准选型<br>- 全息声画绑定与口型动力学参数<br>- **内置毫秒级 SRT 字幕资产** | **【本集视听执行包】**<br>含单镜头 JSON 执行契约、绝对时间轴、内置SRT字幕、集间物理快照。 |
| **阶段 8：多轨智能音频工程与成片混音调度** | `01`时长/风格<br>`04_audio_bible.json` (主题动机)<br>阶段7分镜头执行表 JSON | 阶段7输出的绝对毫秒时间轴与反转静音卡点 | `audio_mastering/`<br>`ep_XX_audio_spec.json`<br>- 单集混音调度标准 JSON 数据契约<br>- 本集定制 Full Master BGM Prompt<br>- 动态分贝增益与静音调度表<br>- NLE 剪辑多轨导入参数规范 | **【本集视听工程最终结项】**<br>交付符合广播级响度与电影级视听质感的最终音频工程规范。 |

---

## 三、 ⚠️ 绝对单向流转、AI 前置自审与双程门控纪律 (State Machine & Audit Law)

1. **第一程绝对不可跨越**：必须在阶段 5 将全季所有集的文学剧本逐集写完并审查定稿，**才允许进入第二程**。严禁在文学剧本未定稿前抢跑做分镜！
2. **第二程单集闭环滚动**：进入第二程后，严格按单集执行【阶段 6 资产准备 ➔ 阶段 7 分镜与SRT ➔ 阶段 8 混音调度】三步闭环。第 XX 集结项后，再自动滚动进入第 XX+1 集。
3. **输出模板一致性**：每次执行必须严格按照标准化 Markdown 结构输出，结尾只有唯一的下一步门控提问。
4. **【强制】红蓝对抗 AI 质量自审与戏剧挑刺机制 (Red-Team Critical Adversarial Audit)**：
   - 彻底打破“既当编剧又当裁判、自己夸自己全打勾”的虚假自审！每次交付人类前，AI 必须强制切换为**【双重视角独立对抗体系】**：
     * **【蓝军（合规审查员 / Compliance Officer）】**：执行客观硬指标检查（时间轴秒数精准累加、资产存在性、格式完备、禁令红线）；
     * **【红军（魔鬼制片人 / 苛刻影评人 Red-Team Critic）】**：**禁止夸奖，专门挑刺！** 强制逐行检索并苛刻指出：
       1. **戏剧张力刺**：哪一句对白有说教/嘴替嫌疑？哪里的反转显得过于配合主角？
       2. **逻辑硬伤刺**：反派是否有降智或行动动机不足？
       3. **视听落地刺**：哪一个镜头的微动作在 AI 视频生成工具中极易穿模融化？
     * **【风险分级与门控动态联动】**：
       - 🔴 **Blocking（阻断级硬伤）**：如严重逻辑硬伤或禁令违规，门控强制拒绝放行，系统必须就地修改；
       - 🟡 **Warning（刺痛改进建议）**：挑出 1-2 处审美/潜台词瑕疵，由人类主创在门控点裁决是否采纳。

---

## 四、 各阶段标准化输出模板规范

### 【第一程：文学故事工程】

#### 阶段 1：题材破壁与创意引擎 (Ideation & Premise)
* **输出规范**：
  ```markdown
  # 【阶段 1 产出：题材破壁与故事动力学】
  ## 一、 项目工程基本盘（全局长期记忆）
  * **剧名（主选/暂定）**：... | **代号**：...
  * **爆款候选片名矩阵（商业吸睛提案，必须提供 6-8 个覆盖四大商业维度的备选）**：
    * **【A. 身份与反常识反差型】**（极高阶/极底层身份错位）：
      1. 《...》
      2. 《...》
    * **【B. 极端悬念与夺命钩子型】**（致命危机与生死倒计时）：
      3. 《...》
      4. 《...》
    * **【C. 核心物证与阶层讽刺型】**（生活微距旧物与社会隐喻）：
      5. 《...》
      6. 《...》
    * **【D. 人格黑化与心理反杀型】**（双面伪装与窒息智斗）：
      7. 《...》
      8. 《...》
  * **题材与类型**：... | **视觉风格**：...
  * **单集规划时长**：...秒 | **画幅模式**：... (竖屏9:16 / 横屏16:9)

  ## 二、 负向双轨禁令清单（全局排异总母集）
  ### 1. 10 大绝对禁止俗套情节（过滤因果逻辑硬伤）
  1. ... 10. ...
  ### 2. 3 大绝对禁止廉价爽点（过滤低幼情绪垃圾）
  1. ... 3. ...

  ## 三、 工业级 Logline 与核心讽刺 (The Dramatic Irony)
  * **核心 Logline**：...
  * **核心讽刺 (Irony)**：...
  * **全剧终极核爆点 (Grand Payoff)**：...

  ---
  ### 🔍【红蓝对抗自审与挑刺报告 (Red-Team Adversarial Audit)】
  * **【蓝军客观合规审查】**：
    - [✓] 禁令排异度：已对照 10 大老套与 3 大廉价爽点进行合规排查；
    - [✓] 商业性评估：候选片名矩阵已覆盖四大商业维度。
  * **【红军魔鬼制片人挑刺 (Red-Team Critic)】**：
    - ⚠️ **戏剧挑刺 1 (概念漏洞)**：[尖锐指出当前故事核中对抗力量是否过于单薄，或主角动机是否显得自嗨]；
    - ⚠️ **戏剧挑刺 2 (俗套倾向)**：[指出哪一个候选片名或情节节点仍有滑入常规套路的危险，并给出刺痛修改建议]。
  * **【综合判定】**：🟢 暂无阻断级缺陷 (No Blocking) / 🟡 存在上述 2 条警示建议供主创裁决。

  ---
  ### 🛑【阶段 1 门控审查点】
  请审查以上题材套路禁令、廉价爽点禁令与故事核心前提，并敲定最终片名：
  - 如果需要调整，请指出具体修改意见；
  - 如果确认无误，请回复“确认无误”，管线将封装【短期记忆A：人设禁令子集 + 核心讽刺】，严格进入【阶段 2：角色人设与心理建模】。
  ```

#### 阶段 2：角色人设与心理建模 (Character Engine, Biological DNA & Relational Dynamics)
* **输出规范**：
  ```markdown
  # 【阶段 2 产出：角色全息人设、肖像DNA、真实生活质感服化道与双轨关系网】
  > 依据阶段 1 核心讽刺与【短期记忆 A：防伟光正/防龙傲天开挂人设红线】，建立全剧角色基因与情感档案：

  ====================================================================================================
  ## 一、 核心角色单体全息 DNA 档案 (必须为阶段 6 单项生图提供 100% 明确的骨相与材质输入)
  ### 角色 [姓名]（[年龄] / [社会身份]）
  1. **【微观生物肖像与骨相 DNA (防塑料假脸与跨集漂移的绝对锚点)】**：
     * **脸型与骨骼架构**：高颧骨/方正下颌/面部折叠度/下巴紧绷感（杜绝整容模板假脸）；
     * **真实皮肤物理质地**：干性/油性真实毛孔分布、眼周细微干纹、皮下毛细血管微泛红反应；
     * **永久面部坐标瑕疵 (DNA 核心防伪)**：精确到毫米级的痣/疤痕坐标（如：右嘴角上方 0.5cm 浅褐色小痣、鼻梁骨性轻微驼峰、脸颊暗红日晒斑）；
     * **眼唇解剖特征**：窄内双/单眼皮眼褶深度、巩膜微血丝分布、瞳孔暗棕色微光、嘴唇常年缺水细小皲裂起皮；
     * **发型与发质**：发际线高度、随意扎低马尾、两鬓带冷雨打湿碎发、发质干枯毛躁微带静电。
  2. **【从头到脚真实生活质感服化道代码 (Lived-in Texture & Fabric Specs - 拒绝崭新塑料布)】**：
     * **外披面料与穿着痕迹**：具体面料材质参数（如重磅粗花呢克重 600g/m²、双面羊绒、洗褪色耐磨卡其布）、手肘弯曲自然折痕、纽扣松脱线头长度（如第二颗纽扣线头松脱下垂 2cm）、下摆干涸泥斑；
     * **内搭细节**：粗棒针针织纹理、领口松弛起球形变与波浪状磨损、领圈内侧汗渍硬壳感；
     * **下装与鞋履**：裤腿直筒水磨白印、工装皮靴/千层底布鞋皮面开裂擦痕、鞋跟磨偏与鞋带起毛；
     * **随身饰品与固有锚定物**：随身佩戴的不可变物品（如发绳、素圈细银戒划痕、包带金属扣氧化绿锈、特定磨砂打火机）。
  3. **【心理动力学四元组】**：Want（外在欲望） / Need（内在救赎） / The Lie（致命谎言） / The Ghost（创伤原罪）。
  4. **【生活阶层轨迹与社会关系】**：成长环境、职业习惯、经济困境与阶层印记。
  5. **【语言与行为指纹】**：短句/长句习惯、口头禅、防御性用语、绝对不说的词、焦虑应激生理动作（如用力摩挲大拇指指甲边缘）。

  ====================================================================================================
  ## 二、 全剧利益与情感双轨关系网络矩阵 (Dual-Track Relationship Matrix)
  | 角色对 (A vs B) | 表面社会身份 | 深层情感牵绊 (爱/恨/负罪/眷恋) | 生死利益死结 (冲突爆发点) | 共同生活旧情物证 (旧情密码) | 动态危险系数 |
  |---|---|---|---|---|---|
  | 主角 vs 核心配角 | ... | ... | ... | [如：红塔山烟盒、白糖发糕、老铜钥匙] | 极度危险 (随时决裂) |
  | 主角 vs 核心反派 | ... | ... | ... | ... | 毁灭级反转点 |
  | 配角 vs 反派 | ... | ... | ... | ... | 利益共谋铁笼 |

  ====================================================================================================
  ## 三、 核心角色全季动态情感流转线路图 (Emotional Arc Trajectory)
  ### 1. [主角姓名] 四阶段情感弧演变：
  * **阶段 A：防御与伪装期 (Guarded & Masked - 0%~25%)**：受致命谎言支配，职业傲慢/自私逃避，防备所有人；
  * **阶段 B：怀疑与裂痕期 (Divergence & Fracture - 25%~50%)**：利益死结撞击，信任断崖式破裂，爆发剧烈对峙；
  * **阶段 C：深渊与自剖期 (Abyss & Confession - 50%~75%)**：绝境降临，谎言崩解，痛哭直面内心原罪与创伤；
  * **阶段 D：超越与悲壮和解期 (Resolution & Catharsis - 75%~100%)**：精神救赎，背水一战，完成向死而生的生死和解。
  ### 2. [核心配角姓名] 四阶段情感弧演变：
  ...（按四阶段输出对应情感轨迹）

  ---
  ### 🔍【红蓝对抗自审与人设挑刺报告 (Red-Team Character Audit)】
  * **【蓝军客观合规审查】**：
    - [✓] 微观生物肖像与骨相 DNA 完备：真实毛孔、毫米级痣/疤坐标、眼唇发质细节已锁定，为阶段 6 彻底杜绝假人与现场脑补；
    - [✓] 真实生活质感服化道代码完备：从头到脚包含面料克重、线头下垂、起球泥斑，拒绝崭新塑料布；
    - [✓] 心理四元组与双轨关系网完备，符合阶段 1 人设禁令。
  * **【红军魔鬼制片人挑刺 (Red-Team Critic)】**：
    - ⚠️ **挑刺 1 (动机虚浮排查)**：[尖锐质询主角的【外在欲望 Want】与【内在需求 Need】是否真正形成生死对立冲突，Lie 是否足够致命，还是依然带有隐性伟光正倾向]；
    - ⚠️ **挑刺 2 (语言指纹同质化排查)**：[逐一对比各角色说话习惯，排查是否所有人都口吻雷同、像编剧自言自语，挑出缺乏辨识度的台词口吻并给出改写建议]；
    - ⚠️ **挑刺 3 (道德两难撕裂度质询)**：[审查核心配角（如周衍）与主角的利益对立，是否真正将角色逼到了无论怎么选都有罪的残酷境地]。
  * **【综合判定】**：🟢 人设骨骼硬朗 / 🟡 存在上述人设张力改进建议，提请主创裁决。

  ---
  ### 🛑【阶段 2 门控审查点】
  请审查以上角色人设及红军挑刺建议：
  - 若红军指出 🔴 Blocking 硬伤，系统必须就地重构人物四元组；
  - 针对 🟡 Warning 建议，请主创选择【采纳修改】或【回复“确认无误，忽略挑刺”】，管线将封装【短期记忆B：角色阶层生活轨迹与随身锚定物】，严格进入【阶段 3：空间设计与物证规划】。
  ```

#### 阶段 3：空间设计与物证规划 (Environments & Props Planning)
* **输出规范**：
  ```markdown
  # 【阶段 3 产出：空间设计与物证规划】
  > 依据阶段 1 时代世界观与【短期记忆 B：角色活动轨迹、随身旧物与真实生活质感服饰代码】，规划核心空间与物证：
  > 💡【场景与服装同源共振铁律】：空间的物理破损与脏旧度必须与阶段 2 角色的服装磨损度（如裤脚泥斑、鞋面油渍）100% 同频，严禁让穿粗布破衣的角色走进干净崭新的样板间！

  ## 一、 核心戏剧空间规划（三层做旧架构）
  * **空间 1 [名称]**：建筑结构层 + 物理生活做旧层（水渍/霉斑/划痕）+ 光影空气介质。
  * **空间 2 [名称]**：...

  ## 二、 核心反转道具规划（物证功能与隐喻）
  * **道具 1 [名称]**：承接阶段 2 随身旧物，规划其在剧中的反转功能、破损形态与物理阻力。
  * **道具 2 [名称]**：...

  ---
  ### 🔍【红蓝对抗自审与物证空间挑刺报告 (Red-Team Environment & Prop Audit)】
  * **【蓝军客观合规审查】**：
    - [✓] 场景具备三层做旧架构（结构层 + 霉斑水渍生活层 + 光影微尘）；
    - [✓] 核心物证具备物理破损尺度、质量阻力感与 +3dB 拟音。
  * **【红军魔鬼制片人挑刺 (Red-Team Critic)】**：
    - ⚠️ **挑刺 1 (道具机械工具人排查)**：[尖锐质询核心物证在当时生活情境中以该形态保存是否违背现实常理，是否沦为编剧强行解密的机械降神道具]；
    - ⚠️ **挑刺 2 (场景阶层隐喻与生活痕迹排查)**：[审查核心空间是否依然带有‘人工搭建样板间’的干净感，是否缺乏底层小城真实的生活压迫感与腐殖质气味]；
    - ⚠️ **挑刺 3 (物理交互破坏可信度质询)**：[审查道具在被撕、砸、切、烧时的形变过程，材质学是否成立，是否缺乏真实阻力感]。
  * **【综合判定】**：🟢 物理资产真实可信 / 🟡 存在道具逻辑改进建议，提请主创裁决。

  ---
  ### 🛑【阶段 3 门控审查点】
  请审查以上空间规划、反转道具及红军挑刺建议：
  - 若红军指出 🔴 Blocking 硬伤，系统必须就地重新设计道具物证与场景；
  - 针对 🟡 Warning 建议，请主创选择【采纳修改】或【回复“确认无误，忽略挑刺”】，管线将封装【短期记忆C：大纲冲突要素包】，严格进入【阶段 4：全季爆款分集大纲规划】。
  ```

#### 阶段 4：全季爆款分集大纲与全剧核心音乐动机母库 (Outlines & Leitmotif Registry)
* **输出规范**：
  ```markdown
  # 【阶段 4 产出：全季爆款分集大纲与全剧音乐动机母库】
  * **全剧季钩 (Season Hook)**：...
  * **中段大危机 (Mid-Season Crisis)**：...
  * **终局核爆终点 (Grand Payoff 对齐)**：...

  ## 一、 全剧核心音乐主题动机母库 (Leitmotif Registry - 阶段 8 BGM 绝对基准)
  （必须依据阶段 1 视觉风格与世界观，锁定 3 个贯穿全剧的具象音乐动机并落盘入 `04_audio_bible.json`）：
  * **【动机 A：悬疑压迫与阶层窒息 (Suspense & Oppression)】**：
    - 配器：准备钢琴（卡硬币金属钝响）+ 40Hz 工矿低频持续震颤 + 机械秒针加速律动；
    - 速度与调性：BPM 85-90，D小调；
    - 戏剧功能：用于日常暗流、对质试探与谎言压制。
  * **【动机 B：情感创伤与负罪救赎 (Emotional Trauma & Guilt)】**：
    - 配器：单音大提琴独奏（Sul Ponticello 弓毛摩擦破损刺耳音）+ 模拟老卡带底噪 (Tape Hiss)；
    - 速度与调性：BPM 65，A小调；
    - 戏剧功能：用于绝笔信物证、至亲痛苦闪回与无声痛哭。
  * **【动机 C：危机反杀与终局撕裂 (Climax & Reckoning)】**：
    - 配器：重失真弦乐断音 (Staccato) + 心跳重低音 (Heartbeat Sub-bass) + 工业金属撞击重音；
    - 速度与调性：BPM 110-120；
    - 戏剧功能：用于撕破脸皮对攻、年会地基投屏与绝杀断点下潜 (Sub-drop)。

  ## 二、 分集大纲表（全 X 集 · 事件与情感双螺旋工笔任务卡）
  > 拒绝抽象一句话大纲！每一集必须是【外部事件链 (Plot)】与【人物关系质变链 (Character)】的双螺旋交织：
  > 💡【外貌破局与阶层线索铁律】：微反转破局点与阶层博弈话题，必须优先调用阶段 2 角色的身体生理瑕疵（如老茧/痣/旧伤）或服装磨损痕迹（如褪色印记/松脱线头）作为戏剧抓手！
  ### 《第 XX 集：[吸睛悬念爆款标题]》（时长：XX 秒）
  * **前 3 秒生死钩子 (Hook)**：第 1 秒必须发生的极端物理异动（具体到动作与物件）
  * **40-60 秒微反转律动 (Micro-Twist)**：具体破局事件与信息颠覆（优先调用阶段 2 身体伤痕或服饰破绽，如：翻开死者满是梭子硬结呈痉挛状的手掌推翻自杀论）
  * **【核心人物关系质变点 (Relational Shift Point)】**：[必须明确写出：本集结束时，主要角色之间的信任、权力对比或情感距离发生了什么不可逆的质变？如：林晚与周衍从旧情试探彻底决裂为利益死敌]
  * **【主角心理谎言崩解度 (The Lie Erosion Metric)】**：[必须标明：阶段 2 设定的致命谎言在本集被现实敲击出了多大一道裂痕？主角付出了什么心理代价？]
  * **本集表面交锋话题 vs 核心试探企图**：[必须借用阶段 2 共同生活旧情密码借题发挥，如：抓着对方褪色警用夹克与高档打火机讽刺其背叛]
  * **集尾绝杀断点 (Cliffhanger)**：动作最高潮的实打实物理生死/利益危机（严禁做梦与误会式虚空诈骗）
  * **涉及核心物证与场景**：[明确调用阶段 3 的具体场景与道具]

  ---
  ### 🔍【阶段 4 红蓝对抗深度挑刺矩阵 (Series Outline Deep Red-Teaming)】
  * **【蓝军客观合规审查】**：
    - [✓] 结构完整性：全季规划总集数达标，每集标题、前3秒Hook、45秒微反转、集尾断点字段 100% 完备；
    - [✓] 终局收敛性：阶段 1 的终极核爆点在全季大结局形成坚实物理收敛，主线无脱轨。
  * **【红军魔鬼制片人专项挑刺矩阵 (Red-Team Critic - 深度排查四大硬伤)】**：
    - ⚠️ **【挑刺 1：注水集与中段塌陷排查 (Filler & Slump Audit)】**：
      [苛刻拷问：全季哪一集去掉后对主线毫无影响？哪一集让主角在原地来回跑腿、事件密度严重不足？（若存在，判定 🔴 Blocking 强制合并删除）]；
    - ⚠️ **【挑刺 2：微反转廉价度与反派降智排查 (Micro-Twist Quality)】**：
      [审查每集 40-60 秒的微反转：这个反转是‘主角凭借智慧与代价博弈出的新局面’，还是‘全靠反派降智、巧合撞见、第三方强行送线索’？]；
    - ⚠️ **【挑刺 3：断点诈骗与虚空危机排查 (Cliffhanger Cheapness)】**：
      [审查集尾绝杀断点：是否存在‘虚空开枪’、‘做梦惊醒’、‘误会式悬念’等廉价诈骗？断点是否具备实打实的物理生死/利益危机？]；
    - ⚠️ **【挑刺 4：全季张力波浪图审计 (Pacing Curve Audit)】**：
      [审查全季中点（如第 6 集）是否出现伪胜利/伪失败的赌注翻倍？危机是否在逐集指数级升级，还是原地踏步？]；
    - ⚠️ **【挑刺 5：情感死水与关系停滞排查 (Relational Stagnation Audit)】**：
      [苛刻审问：连续 2 集之间人物关系是否原地踏步？哪一集的大纲缺少【核心关系质变点】与【谎言崩解度】？若角色只有外部破案跑腿而无情感张力推进，判定 🔴 Blocking 强制重写]。
  * **【综合判定与门控流转】**：
    - 🔴 **Blocking（存在注水集或断点诈骗）**：门控锁死，系统强制就地重写大纲；
    - 🟡 **Warning（反转硬度偏软/中段节奏平缓）**：列出具体情节加码方案，提请人类主创裁决。

  ---
  ### 🛑【阶段 4 门控审查点】
  请审查以上全季各集爆款标题与悬念架构：
  - 如果需要调整某集标题或反转，请提出具体意见；
  - 如果确认无误，请回复“确认无误”，管线将正式进入【阶段 5：全季文学剧本疾速波次连续吞吐】（启动第 1 波次编写：第 01 - 03 集）。
  ```

#### 阶段 5：全季原剧文学剧本疾速波次连续吞吐 (Turbo Mini-Arc Batching & JSON Contract)
* **执行定位：彻底终结单步来回拉扯，按 3-4 集戏剧小高潮单元连续交付结构化 JSON 数据契约**：
  - **消除交互疲劳**：严禁采用每写 1 集停下等一次指令的低效模式！系统必须以 **3-4 集为一个完整的“戏剧波浪单元 (Dramatic Mini-Arc)”**，在单次会话回合中一口气连续输出完整文学原件 JSON 数组；
  - **12 集短剧仅需 3-4 次交互，24 集仅需 6-8 次交互，全季文学即可全量定稿！**
  - **纯 JSON 唯一真理源 (含原始文学原件)**：产出物 100% 固化在单一 JSON 文件中 (`episodes_screenplay/ep_XX.json`)！在 JSON 根节点强制内嵌 `original_screenplay_text` 字段，完整存放排版就绪的影视级标准纯文学剧本文本（带换行符与对白括注），无需做两套文件解析；同时配合 `scenes` 结构化数组，实现“读剧本读此字段，调分镜读数组键值”的零歧义机器级处理；
  - **单元内全自动物理接力**：同一波次内，前一集的集尾绝杀断点最后一秒动作，由系统自动提取并在下一集开场第 1 秒 0 秒咬合 (`previous_episode_physical_pickup`)，无需人工介入衔接；
  - **动笔前三大事前安全护栏（Poka-Yoke Rules - 每集强制作为 JSON 字段固化）**：
    1. **【场面潜台词错位矩阵 (`subtext_matrix`)】**：强制锁定表面掩饰行动 vs 真实企图，设定 3-5 个全场禁词 (`forbidden_words`)，切除嘴替说白；
    2. **【代价与现实毛刺前置锁 (`friction_and_cost_preset`)】**：主角必须承受肉体/利益代价，编织暴雨/打火机卡壳等现实偶发物理毛刺；
    3. **【工笔级任务卡扩写 (`detailed_causal_task`)】**：严格承接阶段 4 任务卡，拒绝凭空盲写。
* **输出规范（按 3-4 集戏剧单元集中交付标准 JSON 数组代码块）**：
```json
[
  {
    "episode_id": 1,
    "episode_title": "第 01 集：[爆款标题]",
    "planned_duration_sec": 120.0,
    "dramatic_arc_unit": "单元 A (第 01 - 03 集) · 开局死局与血信初破壁",
    "core_dramatic_task": "林晚奔丧回乡遭遇全城冷漠，头七夜拆到母亲第七封信发现坠楼实为他杀",
    "original_screenplay_text": "第 01 集：[爆款标题]\n\n【场景 01】内景. 省城调查报社工位 - 黄昏\n百叶窗被夕阳割裂成狭长的暗橘色光栅。角落复印机发出机械的咔哒吞纸声。\n林晚指尖在机械键盘上飞快敲击，屏幕荧光映在泛青眼睑上。桌角放着一杯冷透发黑的苦咖啡。\n倒扣在鼠标垫上的老款手机持续发出沉闷蜂鸣。[声学行为: 开场突发重击 Braam Hit，蜂鸣声转入低频潜流]。\n老郑将一份停刊说明拍在键盘前。林晚敲字的手指骤停，左手大拇指死死掐进食指第二关节。\n\n老郑\n（慢条斯理拧开紫砂保温杯盖，吹了吹浮在面上的枸杞，语气平淡得令人发冷）\n宏昌实业在省城买壳的通稿，明天头条见报。\n\n林晚\n（抬眼直视老郑，后槽牙紧咬，声音冷极而克制，指甲几乎掐出血痕）\n化验所今早被查封了？你收了他们几套房？\n\n【场景 02】内景. 母亲旧公房灵堂与厨房 - 头七深夜\n窗外冻雨沙沙打在单层玻璃上。15W节能灯投下惨绿光晕。林晚戴上塑料手套，美工刀尖划开信封封口。\n信封内掉出一把铜钥匙与药盒纸片。林晚蹲在三只老咸菜坛前，咬牙搬开压菜的大青石，大青石砸在湿水泥地上溅起泥水。\n手臂没入冰冷黏腻的盐水中，从坛底捞出反复封蜡的油纸包。刀刃用力挑开干硬蜂蜡。[声学行为: 核心戏剧骤停，进入主观绝对物理静音 3.0 秒，只留微观刮蜡碎裂声]。\n剥开日记残页，赫然露出当年带血指印与周正国、周衍之父的赔偿金签名。[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！\n\n林晚\n（嘴唇毫无血色，后槽牙死死咬紧，眼泪在眼眶疯狂打转却不下落，字句从齿缝间挤出）\n这不是自杀……这是灭口！",
    "safety_guardrails_lock": {
      "relational_dynamic_lock": {
        "current_emotional_stage": "阶段 A：防御与伪装期 (0%~25%) · 职业傲慢与心防冰封",
        "micro_power_balance": "老郑代表省城体制处于上位施压审判地位；林晚处于下位防御抗争地位，大拇指死掐食指关节外化焦虑",
        "deep_emotional_conflict": "林晚用职业正义的高尚感掩盖自己六年逃避母亲的愧疚，老郑用停刊说明刺破其体面假象",
        "shared_history_props_used": "复印机卡纸声、冷透发黑的苦咖啡、倒扣桌面嗡鸣的老款手机"
      },
      "physical_impedance_metrics": {
        "proxemics_space_distance": "两人相距 2.5 米，中间隔着办公隔板与工位桌面，刻意保持冷淡敌对的安全距离",
        "gaze_aversion_behavior": "老郑吹枸杞回避直视，林晚眼神冰冷死锁老郑，但在听到母亲死讯便签时眼神瞬间散焦下垂45度",
        "tactile_resistance_response": "老郑递便签纸时手指毫无温度直接压在键盘边缘，林晚触碰到纸角时指尖瞬间僵硬收缩",
        "biological_and_costume_triggers": "林晚右手无意识死扯大衣第二颗纽扣松脱下垂2cm的黑线头；老郑视线扫过林晚风衣下摆干结的泥斑，眼神带有一丝隐秘鄙夷"
      },
      "subtext_matrix": {
        "cover_story": "母女整理旧物与借吃冷水饺争论咸淡、要不要关窗的日常琐事",
        "hidden_agenda": "试探对方是否收了工厂封口费，恐吓对方绝不可挖开旧案"
      },
      "forbidden_words": ["谋杀", "封口费", "当年", "秘密", "证据"],
      "protagonist_moral_cost": "林晚小臂被防空洞生锈铁门死死夹伤淤青发紫，被迫直面当年抛弃母亲的冷酷愧疚",
      "incidental_friction": "老式拉丝煤油打火机反复打不着火，窗外突发雷暴大雨声盖过半句关键台词",
      "detailed_causal_task": "严格依据阶段 4 任务卡：从坛底摸出老油纸包，刮开硬蜡，发现盖有周正国签名的质检撕页"
    },
    "previous_episode_physical_pickup": null,
    "scenes": [
      {
        "scene_id": 1,
        "slugline": "内景. 省城调查报社工位 - 黄昏",
        "environment_ref": "ENV_NEWSPAPER_OFFICE",
        "action_lines": [
          "百叶窗被夕阳割裂成狭长的暗橘色光栅。角落复印机发出机械的咔哒吞纸声。",
          "林晚指尖在机械键盘上飞快敲击，屏幕荧光映在泛青眼睑上。桌角放着一杯冷透发黑的苦咖啡。",
          "倒扣在鼠标垫上的老款手机持续发出沉闷蜂鸣。[声学行为: 开场突发重击 Braam Hit，蜂鸣声转入低频潜流]。",
          "老郑将一份停刊说明拍在键盘前。林晚敲字的手指骤停，左手大拇指死死掐进食指第二关节。"
        ],
        "dialogues": [
          {
            "dialogue_id": "D01",
            "speaker": "老郑",
            "parenthetical": "慢条斯理拧开紫砂保温杯盖，吹了吹浮在面上的枸杞，语气平淡得令人发冷",
            "subtext_intention": "通知封口与试探林晚的服从度",
            "lines": "宏昌实业在省城买壳的通稿，明天头条见报。"
          },
          {
            "dialogue_id": "D02",
            "speaker": "林晚",
            "parenthetical": "抬眼直视老郑，后槽牙紧咬，声音冷极而克制，指甲几乎掐出血痕",
            "subtext_intention": "直接点破对方受贿，寸步不让",
            "lines": "化验所今早被查封了？你收了他们几套房？"
          }
        ]
      },
      {
        "scene_id": 2,
        "slugline": "内景. 母亲旧公房灵堂与厨房 - 头七深夜",
        "environment_ref": "ENV_MOTHER_APARTMENT_NIGHT",
        "action_lines": [
          "窗外冻雨沙沙打在单层玻璃上。15W节能灯投下惨绿光晕。林晚戴上塑料手套，美工刀尖划开信封封口。",
          "信封内掉出一把铜钥匙与药盒纸片。林晚蹲在三只老咸菜坛前，咬牙搬开压菜的大青石，大青石砸在湿水泥地上溅起泥水。",
          "手臂没入冰冷黏腻的盐水中，从坛底捞出反复封蜡的油纸包。刀刃用力挑开干硬蜂蜡。[声学行为: 核心戏剧骤停，进入主观绝对物理静音 3.0 秒，只留微观刮蜡碎裂声]。",
          "剥开日记残页，赫然露出当年带血指印与周正国、周衍之父的赔偿金签名。[声学行为: 终局下潜重击 Sub-drop 随黑屏骤停]！"
        ],
        "dialogues": [
          {
            "dialogue_id": "D03",
            "speaker": "林晚",
            "parenthetical": "嘴唇毫无血色，后槽牙死死咬紧，眼泪在眼眶疯狂打转却不下落，字句从齿缝间挤出",
            "subtext_intention": "认清母亲被谋杀的血淋淋真相与巨大的心理崩溃",
            "lines": "这不是自杀……这是灭口！"
          }
        ]
      }
    ],
    "dramatic_rhythm_check": {
      "hook_3s": "开场第 1 秒倒扣手机桌面剧烈震动蜂鸣，老郑将红印停刊说明重重拍在键盘上",
      "micro_twist_45s": "第 45 秒坛底摸出的不是遗书，而是盖有周正国签名的二十年前事故质检撕页与带血指印",
      "cliffhanger_end": "林晚在死寂厨房捏紧药盒纸片浑身发颤，远方厂区试鸣夜班汽笛如尖叫般撕裂夜空"
    },
    "episode_end_physical_delta": {
      "character_pose": "林晚瘫坐在厨房满地泥水与散乱芥菜叶中，左手将药盒纸片死死按在胸口，右手撑在湿冷地面发抖",
      "held_prop": "左手指缝夹着带血日记撕页角，右手掌心满是陶土坛褐色盐霜污渍",
      "environment_state": "旧公房厨房角落，最大的陶土坛大青石摔在一侧地面，节能灯光晕闪烁微弱电流声"
    },
    "audit_report": {
      "blue_team_compliance": {
        "show_dont_tell_pass": true,
        "parenthetical_speech_mechanics_complete": true,
        "inter_episode_physical_pickup_aligned": true,
        "json_schema_valid": true
      },
      "red_team_criticism": {
        "subtext_iceberg_test": "老郑与林晚全场未提‘行贿受贿’具体条款，借由枸杞茶与通稿见报完成试探，潜台词冰山层次丰富",
        "moral_cost_audit": "林晚失去了大报社记者证与体面退路，且被迫直面六年不回家的道德原罪，代价真实沉重",
        "antagonist_competence": "老郑态度极度从容冷漠，展现体制与资本合谋的无形铁壁，无降智狂怒",
        "incidental_friction": "复印机吞纸卡壳声与冷透咖啡的油膜微观毛刺编织自然",
        "relational_amnesia_audit": "林晚对老郑由抵触到瞬间心防破裂，站位距离2.5米与眼神回避45度严格执行物理外化，无情感失忆",
        "biological_costume_anchoring": "动作行严格调用了林晚第二颗纽扣下垂线头拉扯动作，老郑喝茶吹枸杞与其体制紫砂杯锚定物完全契合，无凭空悬浮动作"
      },
      "verdict": "GREEN_APPROVED"
    }
  },
  {
    "episode_id": 2,
    "episode_title": "第 02 集：[爆款标题]",
    "planned_duration_sec": 120.0,
    "dramatic_arc_unit": "单元 A (第 01 - 03 集) · 开局死局与血信初破壁",
    "core_dramatic_task": "林晚拒绝签字火化母亲遗体，在太平间外与周衍爆发关于生存与真相的初次对峙",
    "safety_guardrails_lock": {
      "subtext_matrix": {
        "cover_story": "讨论拆迁分房指标、安葬开销由厂里全包与天气寒冷",
        "hidden_agenda": "周衍奉命替全城利益链筑防线劝退林晚，林晚拿尸检伤情反向撕开体面假象"
      },
      "forbidden_words": ["他杀", "推下去", "封口", "包庇", "害怕"],
      "protagonist_moral_cost": "林晚当场退掉回省城的高铁票，被县医院工作人员与老邻里当成异类排斥",
      "incidental_friction": "冷风吹灭周衍手中的打火机，排气管突突冒出的浓烈刺鼻废气",
      "detailed_causal_task": "周衍递过火化确认书，林晚翻出尸检图解，点破枕骨与跟腱伤情角度异常"
    },
    "previous_episode_physical_pickup": {
      "character_pose_pickup": "林晚从厨房泥水中站起，换上黑色风衣，帆布鞋面残留昨夜干涸发黑的盐水渍",
      "held_prop_pickup": "母亲留下的生锈铜钥匙系在红绳上挂入内衣贴身口袋，随身携带黑色旅行袋",
      "environment_pickup": "清晨浓雾笼罩的县城老火车站至县医院太平间后门碎石路"
    },
    "scenes": [],
    "dramatic_rhythm_check": {},
    "episode_end_physical_delta": {},
    "audit_report": {}
  }
]
```

* **🛑 阶段 5 戏剧波次文学审查门控点**：
  请审查本单元（第 XX - YY 集）结构化文学剧本 JSON 数组及红蓝挑刺报告：
  - 若需修改个别台词括注或情节动作，提出具体字段修改意见；
  - 若确认无误：
    * **【若 YY < 全季总集数】**：请回复“确认无误，推进第 YY+1 至 ZZ 集”，管线将自动启动下一波次连续吞吐！
    * **【若 YY == 全季总集数】**：请回复“全季文学剧本定稿，进入第二程”，管线将封装全量文学 JSON，正式启动【阶段 6：分集按需资产准备】！

#### 阶段 6：分集增量视听资产提取与单项素材生成 (Incremental Asset Extraction & Generation)
* **定位**：阶段 6 不生成复杂角色组合母板，也不把多个摄影尺度塞进一张 AI 图；本阶段按当前集需求，生成可直接用于分镜的视频生产素材，并注册到全局资产库。
* **输出边界**：阶段 6 只负责需求扫描、资产缓存查询、缺失资产生成、审核注册和本集引单；不负责生成完整全局资产说明，也不负责具体镜头分镜。
* **执行原则**：每集都执行“扫描需求 → 查询资产 → 复用合格资产 → 对缺失项执行子流程 → AI审核 → 注册资产 → 输出本集资源引单”，但**已有合格资产不得重复生成**。
* **全局唯一真理源**：`05_visual_audio_assets.json`。已批准资产只读继承；状态变化建立新分支，不覆盖基础资产。
* **读取输入（长短期记忆动态装配）**：
  - **长期记忆**：`01_bible.json`（题材、类型、风格、时代、画幅、负向双轨禁令、核心讽刺）+ `02_characters.json`（角色 DNA、心理、语言、基础服饰、锚定物）+ `03_environments_props.json` + `04_audio_bible.json` + 第一程已定稿文学剧本全集；
  - **短期记忆**：当前集文学剧本、当前集任务卡、上一集集尾物理快照（姿态、伤势、服装破损、持有道具、空间位置、光线）；
  - **剧情上下文**：扫描当前集所有场景、角色、动作、道具、实际情绪、服装状态、光线和对白/旁白需求；全季剧本只用于角色情绪谱和状态连续性分析，不把全集全文无差别塞入生成 Prompt。

##### 6.1 风格动态编译器 (Style Compiler)
根据 `01_bible.json` 的项目基本盘选择唯一风格介质，所有阶段 6 图片必须使用同一风格配置：

| 项目风格 | 正向视觉介质 | 禁止混入的介质 |
|---|---|---|
| 真人电影/超写实 | natural human proportions, unretouched photographic realism, authentic skin texture, real lens behavior | anime, cartoon, CGI, plastic skin, airbrushed beauty face |
| 2D动漫/国漫 | hand-drawn 2D linework, controlled cel shading, illustrated anatomy, consistent character design | photorealistic skin pores, live-action film still, realistic camera grain |
| 赛博朋克/美漫 | graphic-novel linework, controlled neon palette, stylized ink shadows, coherent cyberpunk design | random photorealism, pastel children illustration, incompatible period style |
| 国风水墨/古典 | ink-wash linework, mineral pigments, silk and linen texture, controlled brushwork | modern streetwear, neon cyberpunk, plastic 3D render |

* **强制规则**：真人项目才可使用毛孔、皮下血色、胶片和真实镜头词；非真人项目不得混入真人摄影词。风格负向词在阶段 6 和阶段 7 均须继承。

##### 6.2 当前集需求扫描与资产缓存查询
先建立本集需求表，再逐项查询全局注册表：

```text
当前集文学稿
  → 角色清单：出场者、视角、情绪、服装状态、光线、伤势
  → 场景清单：独立时空、时间、空间状态、光源
  → 道具清单：出现、持有者、交互动作、状态
  → 旁白/对白清单：说话者、TTS、预计时长
  → 查询05_visual_audio_assets.json
      ├─ APPROVED：直接复用
      ├─ APPROVED但状态不匹配：建立状态分支
      ├─ 存在但REJECTED：禁止引用，重新生成
      └─ 不存在：启动对应单项素材子流程
```

每项资产必须标注：`asset_id`、`type`、`status`、`first_episode`、`source_reference`、`style_profile`、`aspect_ratio`、`usage`。重复出现的角色、场景和道具必须直接引用原 `asset_id`，不得重新起名或重新随机生成。

##### 6.3 单项素材生成子流程（必须按需执行）

**A. 首次角色身份基准图**（只在角色首次出现且总库没有时执行）

```text
直接读取 02_characters.json 中阶段 2 锁定的【生物肖像骨相 DNA】与【生活质感服化道代码】+ 风格配置
→ 严禁现场脑补！必须 1:1 翻译阶段 2 设定的高颧骨、窄内双、毫米级痣坐标与做旧面料参数
→ 生成单人、自然表情、中性背景、自然光身份基准图
→ 审核真人/目标风格、年龄、脸型、发型、皮肤微观瑕疵、固定特征
→ APPROVED后注册 CHAR_<ID>_BASE_PORTRAIT
```

不得加入复杂动作、多人、组合排版、文字标签或夸张表情。该图只负责锁定身份，不直接替代所有镜头素材。

**B. 四视图独立全身生产图**

分别执行四次图生图/角色参考生成：

```text
CHAR_<ID>_FRONT_FULL
CHAR_<ID>_PROFILE_FULL
CHAR_<ID>_3Q_FULL
CHAR_<ID>_BACK_FULL
```

输入关系：

```text
主输入：对应视角的单项初始图或角色参考图
身份参考：CHAR_<ID>_BASE_PORTRAIT
继承：角色DNA、发型、体型、固定服饰、锚定物
唯一变化：视角
```

强制要求：单人、全身、从头顶到鞋底、鞋底可见、无脚部裁切、自然人体比例、无拼贴、无展板、无文字、无其他人物。四张图可使用不同用途画幅，必须记录实际 `aspect_ratio`；不得为了统一而强制使用 21:9。

**C. 剧本实际情绪生产图**

扫描全季剧本与当前集任务，选择角色真实出现且本集需要的情绪，不机械套用喜怒哀乐：

```text
全季情绪谱 + 当前集情绪节点
→ 生成单人面部/胸部以上单项图
→ 使用身份基准图作参考
→ 只改变表情，不改变身份、发型、服装和光线设定
```

每个情绪必须记录：`emotion_id`、剧本出处、肌肉变化、强度（1-5）、是否本集使用。没有大笑就不生成大笑；只有微笑就生成低幅度、闭口或轻微嘴角上扬的自然微笑。禁止动漫式张嘴、夸张泪崩和过度拉伸五官。

**D. 光感生产图**

只有剧本或分镜需要时才生成：

```text
CHAR_<ID>_LIGHT_NEUTRAL
CHAR_<ID>_LIGHT_LOWKEY
CHAR_<ID>_LIGHT_HARSH
```

使用同一身份基准图和当前服装参考，原则是只改变光源、色温、阴影和反光，不改变脸型、发型、年龄、服装和固定装饰。光感图是单项参考图，不与四视图或表情图混生成。

**E. 服饰与装饰生产图**

按镜头需要生成：

```text
CHAR_<ID>_COSTUME_FULL
CHAR_<ID>_COSTUME_INNER
CHAR_<ID>_COSTUME_MACRO
CHAR_<ID>_ACCESSORIES_MACRO
```

服饰 Prompt 必须从头到脚描述外披、内搭、下装、鞋履、缝线、面料、磨损、纽扣、拉链和装饰物。服装状态不能凭空改变；换装、湿身、污损、破裂只能建立状态分支。

**F. 生理微距生产图**

按分镜需要生成：

```text
CHAR_<ID>_HAND_MACRO
CHAR_<ID>_EYE_MACRO
CHAR_<ID>_MOUTH_MACRO
```

使用身份基准图和角色固定特征作参考，单独处理手指、戒指、创可贴、眼褶、眼白血丝、嘴角痣和唇纹。禁止把手部、眼唇微距与全身或多表情放在同一生产图中。

**G. 状态分支生产图**

当前集若发生负伤、湿身、污损、换装或道具状态变化，建立：

```text
CHAR_<ID>_STATUS_<STATE>
PROP_<ID>_STATE_<STATE>
ENV_<ID>_STATE_<STATE>
```

状态分支必须继承基础资产的身份 DNA、服饰逻辑、锚定物、场景结构和项目风格；只增加本集发生的变化，不能覆盖原始基础资产。

**H. 场景资产分级与剧本动态生成子流程 (Script-Driven Environment Generation)**

严禁默认给每个场景跑全景、过肩、空镜及多时态全套图！严格依据本集文学剧本场面调度动态按需触发：
1. **分级标准**：
   - **一级核心主场景（发生 >= 3 场戏）**：按剧本镜头需要生成资产；
   - **二级过渡次场景（仅出现 1-2 镜，如车内后座、走廊、门口斜坡）**：仅生成 1 张单项关键帧背景图，严禁铺张建档。
2. **剧本镜头动态触发规则（剧本没写坚决不生）**：
   - `ENV_<ID>_WIDE`（全景建立图）：仅当剧本动作行明确出现“大远景、建筑全貌、环境建立”时触发；
   - `ENV_<ID>_OTS_BG`（过肩对白景深板）：仅当本场为“两人近距离对坐多轮对白交锋”且需背景虚化时触发；
   - `ENV_<ID>_INSERT`（空间局部空镜）：仅当剧本动作行明确有“特写空镜叙事（如滴水龙头、停摆挂钟）”时触发；
   - `ENV_<ID>_STATE_<TIME>`（光影时态分支）：仅当时间线推进出现跨时段重大光影突变（日/夜/暴雨）或空间损毁（火灾/被抄）时增量注册，白天戏没拍完绝不提前生夜戏。

**I. 道具资产分级与剧本形态动态生成子流程 (Script-Driven Prop Generation)**

严禁给每根牙签、水饺建档！严格依据本集角色手部交互动词动态按需触发：
1. **分级标准**：
   - **一级核心叙事物证（推动反转的关键物证，如血信、存折、带血安全帽、录音带）**：出具专属微距图与物理参数；
   - **二级角色锚定道具（打火机、金戒、创可贴、核桃）**：直接并入角色的 `HAND_MACRO` 手部特写资产，不单独占道具配额；
   - **三级环境气氛杂物（冷水饺、茶杯、螺丝刀、碗筷）**：零独立生图！仅在分镜 Prompt 作动词交互描述。
2. **剧本动词动态触发形态规则（没被破坏绝不生两态）**：
   - `PROP_<ID>_STATIC`（静态微距图）：当且仅当角色有直接手持、查看动作时生成 1 张；
   - `PROP_<ID>_ACTION`（破坏/交互态图）：**只有且仅当剧本动作行出现“撕、砸、切、折、烧、撬”等形变动词时**，才触发生成破坏态图，与静态图组成首尾帧配对；物件未被破坏严禁生成第二态！
   - **强制标注物理阻力与拟音**：核心道具必须标注质量阻力感（如“大青石重30斤，双手青筋暴起，粗糙刮擦阻力”）与专属 +3dB 拟音指令。

##### 6.4 资产审核与注册
每一张图片在进入总库前必须经过 AI 质量总监审核：

```text
生成单项素材
→ 风格一致性检查
→ 人物身份一致性检查
→ 构图与用途检查
→ 真实度/自然度检查
→ 服饰与装饰检查
→ 物理状态连续性检查
→ APPROVED / REJECTED
→ 只有APPROVED才注册并供阶段7引用
```

REJECTED 的典型原因：真人项目出现塑料皮肤、表情夸张、脸型漂移、脚部缺失、服装缺失、光线与项目风格冲突、背景残留展板或文字、手部畸形、与上集状态冲突。

##### 6.5 阶段 6 固定输出模板

```markdown
# 【阶段 6 产出：第 XX 集视听资产增量提取与单项素材注册表】
## 《第 XX 集：[爆款标题]》
* 项目风格：...
* 当前集需求：角色 X 位 | 场景 Y 个 | 道具 Z 件 | 新增资产 ... 件
* 全局资产库版本：...

### 一、本集资产需求扫描
| 类别 | 名称 | 当前状态 | 需要的素材 | 处理方式 |
|---|---|---|---|---|

### 二、已注册资产复用清单
| 资产ID | 类型 | 当前集用途 | 文件 | 状态 |
|---|---|---|---|---|

### 三、新增/状态分支单项素材
#### 资产 [ID]
* 来源参考图：...
* 生成子流程：身份基准/四视图/剧本情绪/光感/服饰/微距/状态分支
* 生成Prompt：...
* 图生图输入：...
* 风格配置：...
* 画幅与用途：...
* 审核状态：...

### 四、本集阶段7资源引单（按类别分列，不合并展示；角色按三级资产归类）
#### 4.1 角色资源（按三级角色资产归类）
##### 一级：身份基础资产
| 角色ID | 角色名 | 基础身份图 | 基础服装图 | 本集用途 | 状态 |
|---|---|---|---|---|---|

##### 二级：叙事表现资产
| 角色ID | 角色名 | 角度图 | 剧本情绪图 | 行为/服装状态 | 本集用途 | 状态 |
|---|---|---|---|---|---|---|

##### 三级：镜头专项资产
| 角色ID | 角色名 | 专项类型 | 专项资产ID/文件 | 触发镜头 | 状态 |
|---|---|---|---|---|---|

#### 4.2 场景资源（按两级场景分类）
##### 一级核心主场景（发生 >= 3 场戏）
| 场景ID | 场景名 | 景别类型(建立全景/过肩景深/局部空镜) | 光影时态 | 关键帧文件/Prompt | 状态 |
|---|---|---|---|---|---|

##### 二级过渡次场景（仅出现 1-2 镜，单张关键帧）
| 场景ID | 场景名 | 关键帧文件/Prompt | 当前光线与空间状态 | 状态 |
|---|---|---|---|---|

#### 4.3 道具资源（按三级道具分类）
##### 一级核心叙事物证（推动反转的关键物证，支持形态双图）
| 道具ID | 道具名 | 形态(静态初始态/破坏交互态) | 物理阻力与+3dB拟音 | 微距文件/Prompt | 状态 |
|---|---|---|---|---|---|

##### 二级角色锚定道具（打火机/戒指/手表，已并入角色 HAND_MACRO）
| 道具ID | 道具名 | 所属角色 | 绑定的角色手部微距资产ID | 状态 |
|---|---|---|---|---|

##### 三级环境气氛杂物（茶杯/冷水饺/螺丝刀）
| 杂物名 | 所在场景 | 动词交互描述 (零图片生成，仅提示词驱动) | 拟音标注 |
|---|---|---|---|

#### 4.4 声音资源
| TTS资产ID | 角色/旁白 | 声音状态 | 对应对白/旁白 |
|---|---|---|---|

> 引单规则：角色、场景、道具、声音分别列示；角色资源必须按一级、二级、三级归类；本区只登记 APPROVED 资产；已注册资产沿用原ID，状态变化使用状态分支ID。

### 五、红蓝对抗自审与单项资产挑刺报告 (Red-Team Asset Audit)
* **【蓝军客观合规审查】**：
  - [✓] 资产分类与复用：角色三级、场景两级、道具三级归类完整，已有合格资产 100% 继承复用，无重复随机生成；
  - [✓] 四视图与微距指标：全身四视图从头到脚完整无脚底裁切，核心物证阻力感与拟音标注完整；
  - [✓] 注册状态：所有合格素材已合流登记至 `05_visual_audio_assets.json`。
* **【红军魔鬼概念设计师挑刺 (Red-Team Critic)】**：
  - ⚠️ **挑刺 1 (真实度与AI假人感排查)**：[尖锐审视新生成角色图是否依然带有网红磨皮、过亮眼神光或塑料假脸痕迹，微观生物瑕疵是否足够真实]；
  - ⚠️ **挑刺 2 (微表情剧本相关性挑刺)**：[苛刻检查本集提取的微表情是否真正来自文学剧本实际冲突，是否存在脱离剧本的浮夸大笑或动漫式大哭]；
  - ⚠️ **挑刺 3 (资产冗余度挑刺)**：[排查本集是否有未被分镜镜头调用的多余图片生成，道具三级杂物是否违规生成了独立图片]。
* **【综合判定】**：🟢 资产精简逼真 / 🟡 存在上述质感优化建议，提请主创裁决。

### 🛑阶段6资产门控
全部资产通过后回复“确认无误”，进入阶段7；否则只补齐或重生成不合格资产。
```

#### 阶段 7：逐集单镜头工业执行表生成 (Shot-by-Shot Storyboard Script)
* **执行定位：从松散 Markdown 升级为机器可解析的工业级 JSON 契约 (Machine-Readable JSON Contract)**：
  - 本阶段直接输出结构严格、语义完备的 JSON 数据对象，可直接供 Python 脚本、ComfyUI、自动化生成流水线解析分发；
  - **严密双模式选型决策法则（有理有据，彻底杜绝 AI 视频崩溃畸变）**：
    每个镜头必须且只能明确指定属于【模式 A 首尾帧模式】或【模式 B 多图参考模式】之一，依据以下黄金决策树判定：
    * **【模式 A：首尾帧模式 (first_last_frame)】—— 专治物体破坏、位移突变与机械开合**：
      - *适用场景*：凡涉及“撕裂、砸碎、切开、折断、烧毁”等不可逆物理形变；门窗铁柜从关到猛开；角色从站立到扑倒或 180 度大转身；
      - *生成链条*：必须三步闭环提供：① 首帧文生图 Prompt (`first_frame_prompt`) ➔ ② 尾帧文生图 Prompt (`last_frame_prompt`) ➔ ③ 首尾帧图生视频运动 Prompt (`video_motion_prompt`)；
      - *禁忌*：**严禁在长时间对白与细腻微表情镜头中使用首尾帧**（否则落幅强约束会导致人物面部拉扯抽搐融化！）；
    * **【模式 B：多图参考模式 (multi_image_reference)】—— 专治对白交锋、神态微表情与过肩对峙**：
      - *适用场景*：角色正面/侧面说话、咬牙压抑、眼神回避、心理暗流与过肩正反打；
      - *生成链条*：必须明确提供：① 引用的 APPROVED 单项资产 ID 数组 (`reference_assets`) ➔ ② 注入解剖发声肌肉联动的多图生视频 Prompt (`multi_image_video_prompt`)；
      - *禁忌*：**严禁在剧烈物理破坏镜头中使用纯多图参考**（否则模型无法做出实打实的撕裂位移）。
  - **全息声学提示词全量规范（除 BGM 外的所有声音均通过提示词实现）**：
    * 对白/旁白：必须结合阶段 4 声纹基准与阶段 5 呼吸括注，输出带声纹 ID、声带闭合腔体指令、呼吸停顿断句与字句重音的完整 Prompt；
    * 拟音 Foley：具体摩擦、水渍、金属磕碰声，明确标注 +2dB~+3dB 增益；
    * 口型动力学：显式标注下颌开度限制 (Jaw Scale: 咬牙0.4~0.5 vs 呼喊0.8~0.9)、嘴角张力与头部微动。
* **读取输入（长短期记忆动态装配）**：
  - 当前集文学剧本 `episodes_screenplay/ep_XX.json` + 阶段 6 资源引单 + `05_visual_audio_assets.json` (仅 APPROVED 单项素材) + 阶段 5 任务卡 + 上一集物理快照。
* **输出规范（纯净工业级 JSON 代码块呈现）**：
```json
{
  "episode_id": 1,
  "episode_title": "第 XX 集：[爆款标题]",
  "planned_duration_sec": 120.0,
  "aspect_ratio": "9:16",
  "resource_manifest": {
    "characters": [
      {
        "character_id": "CHAR_LINWAN",
        "name": "林晚",
        "level": "tier_1_base / tier_2_performance / tier_3_special",
        "used_assets": ["CHAR_LIN_4V_FRONT", "CHAR_LIN_EXP_GRIEF", "CHAR_LIN_HAND_MACRO"]
      }
    ],
    "environments": [
      {
        "environment_id": "ENV_01",
        "name": "旧公房灵堂",
        "level": "tier_1_primary / tier_2_transitional",
        "used_asset": "ENV_01_KEYFRAME_NIGHT"
      }
    ],
    "props": [
      {
        "prop_id": "PROP_01",
        "name": "老咸菜坛与血信",
        "level": "tier_1_hero_prop / tier_2_anchor / tier_3_atmospheric",
        "used_assets": ["PROP_01_STATIC", "PROP_01_ACTION"]
      }
    ],
    "audio": {
      "tts_profiles_used": ["VOICE_LIN_COLD_MEZZO"],
      "foley_focus": "+3dB 刀尖刮蜡划擦声, 大青石砸地钝响"
    }
  },
  "shots": [
    {
      "shot_id": 1,
      "timecode": "00:00:00,000 --> 00:00:02,500",
      "duration_sec": 2.5,
      "framing": "ECU 极微距",
      "camera_motion": "Slow Push-in (缓慢微推进)",
      "generation_mode": "first_last_frame",
      "selection_rationale": "剧本动作涉及美工刀划开硬蜡的物理形变破坏，属于模式A首尾帧必选场景",
      "first_last_frame_config": {
        "first_frame_asset_ref": "PROP_01_STATIC",
        "first_frame_prompt": "Cinematic macro shot, sharp focus, 35mm film still. A rusty utility knife blade touches the thick dark-red wax seal of an antique earthenware pickling jar, fingers wrapped with scuffed white medical tape. Gloomy green fluorescent lighting, --ar 9:16 --style raw",
        "last_frame_asset_ref": "PROP_01_ACTION",
        "last_frame_prompt": "Cinematic macro shot, knife blade slicing through cracked red wax seal, wax chips splintering into air, revealing the corner of dark dried-blood stained paper underneath, --ar 9:16 --style raw",
        "video_motion_prompt": "Slow continuous push-in. The utility knife blade firmly slices downward through the brittle wax seal, micro-vibrations on blade, wax fragments bursting outward in slow motion, camera moves smoothly closer to reveal the stained paper corner."
      },
      "audio": {
        "voice_type": "voiceover",
        "character_name": "旁白",
        "voice_prompt": "[VOICE: NARRATOR_COLD_BASS] Resonant dry baritone, extremely fast and chilling cadence, tight vocal cords with deep vocal fry. Script: '有些信……(吞咽停顿0.2s) 拆开就得拿命填。'",
        "foley_prompt": "Sharp piercing metallic blade scratching on hardened beeswax, followed by subtle brittle wax snapping sound (+3.0 dB boost)."
      },
      "lipsync_dynamics": null
    },
    {
      "shot_id": 2,
      "timecode": "00:00:02,500 --> 00:00:05,500",
      "duration_sec": 3.0,
      "framing": "MCU 中近景",
      "camera_motion": "Static Gaze (静止冷峻凝视)",
      "generation_mode": "multi_image_reference",
      "selection_rationale": "剧本属于核心对白与咬牙隐忍神态表演，属于模式B多图参考必选场景，严禁使用首尾帧防面部抽搐",
      "multi_image_config": {
        "reference_assets": [
          "CHAR_LIN_4V_FRONT",
          "CHAR_LIN_EXP_GRIEF",
          "CHAR_LIN_LIGHT_CHIAROSCURO",
          "ENV_01_KEYFRAME_NIGHT"
        ],
        "multi_image_video_prompt": "Static shot, eye-level. Lin Wan speaks through tightly clenched teeth: her clamped jaw twitches with masseter muscle bulging, lower lip quivers with genuine tearful agony, neck tendons visibly strain on the word '灭口', single tear wells up in red swollen waterline without falling. Subtle breath exhaust from nostrils."
      },
      "audio": {
        "voice_type": "dialogue",
        "character_name": "林晚",
        "voice_prompt": "[VOICE: LIN_COLD_MEZZO] 28-year-old female investigative journalist, dry vocal texture, mid-low pitch. Clamped jaw speech mechanics, 35% breathy vocal fry. Script: '(深吸一口发颤凉气0.3s) 这不是自杀……(后槽牙咬死喉音重音) 这是灭口！'",
        "foley_prompt": "Subtle tweed wool collar friction (-6dB) accompanied by sharp cold inhalation sound."
      },
      "lipsync_dynamics": {
        "target_face_asset": "CHAR_LIN_4V_FRONT",
        "jaw_open_scale": 0.45,
        "lip_tension": "High (clamped corners, restricted movement)",
        "head_motion": "Slight 2-degree downward tilt, eyes snap up to lock with camera on the final word."
      }
    }
  ],
  "inter_episode_physical_delta": {
    "character_pose": "林晚半跪在地，重心前倾，右手紧握美工刀卡在坛口边缘",
    "held_prop": "左手两指夹着带血日记撕页角，药盒纸片贴在胸口大衣内侧",
    "environment_state": "旧公房厨房角落，陶土坛大青石被搬开摔在水泥地一侧，泥水溅在鞋面"
  },
  "srt_export": "1\n00:00:00,000 --> 00:00:02,500\n【旁白】有些信，拆开就得拿命填。\n\n2\n00:00:02,500 --> 00:00:05,500\n【林晚】这不是自杀……这是灭口。\n",
  "audit_report": {
    "blue_team_compliance": {
      "timecode_sum_exact": true,
      "total_duration_sec": 120.0,
      "all_shots_under_4_5s": true,
      "asset_legality_100_percent": true,
      "srt_timecode_aligned": true
    },
    "red_team_criticism": {
      "ai_distortion_risk": "镜号 01 刀刃划开硬蜡动作已通过首尾帧模式完全约束，无穿模形变风险；镜号 02 对白戏锁定多图参考，下颌开度已限制为 0.45，无大张嘴崩坏风险",
      "pacing_rhythm": "镜号 01 极微距与镜号 02 中近景交替，视听节奏紧凑，呼吸感良好",
      "lipsync_realism": "林晚发声前兆包含倒吸凉气与喉头吞咽动作，解剖发声联动完整"
    },
    "verdict": "GREEN_APPROVED"
  }
}
```

* **🛑 阶段 7 单集审查门控点**：
  请审查第 XX 集单镜头工业 JSON 执行包（包含首尾帧/多图配置、全息声学指令与 SRT 字幕）：
  - 若需调整某个镜头的模式选择或提示词，请提出修改意见；
  - 若确认无误，请回复“确认无误”，管线将封装该 JSON 中的时间轴与音频数据，严格进入【阶段 8：第 XX 集多轨智能音频工程与成片混音调度】！

#### 阶段 8：多轨智能音频工程与成片混音调度 (Intelligent Audio Mastering & Mixing Engine)
* **定位**：本阶段为全剧视听工程的“终极混音控制台”。拒绝泛泛背景音乐，依据阶段 7 锁定的绝对毫秒时间轴与戏剧反转点，智能定制 BGM 生成 Prompt、计算动态分贝避让曲线与断崖静音卡点，并输出开箱即用的剪辑轨道混音导入参数规范，为剪映、CapCut、Premiere、DaVinci 等剪辑工具提供专业的音频工程指导。
* **读取输入（绝对时间轴与声学继承）**：
  - **长期记忆**：`01_bible.json`（单集绝对时长、项目视觉风格）+ `04_audio_bible.json`（全剧核心音乐主题动机 Leitmotif、拟音放大规范）；
  - **短期输入**：阶段 7 锁定的本集单镜头执行表（包含每个镜头的动作性质与时间码）+ 阶段 7 导出的标准 SRT 字幕文件（作为人声语音避让的时间掩码）。
* **四大智能化音频处理准则**：
  1. **【分段戏剧化 BGM Prompt 动态编译】**：严格锁定单集时长（如 120s），依据前 3 秒 Hook、45 秒微反转、集尾断点，分段生成适配 Suno / Udio / 本地音乐模型的结构化提示词；
  2. **【动态分贝增益与智能语音避让 (Audio Ducking)】**：
     - **对白语音区**：BGM 自动衰减至 `-18dB ~ -22dB`，确保对白达到 -23 LUFS 广播级清晰度；
     - **纯动作与悬疑区**：BGM 自动平滑拉升至 `-10dB ~ -12dB`，强化视听压迫感；
     - **突发撞击点**：瞬态提升至 `-6dB`；
  3. **【断崖式主观静音法则 (Drop to Absolute Silence)】**：在阶段 4/7 标注的重大反转点（如点破秘密、至亲背叛），强制执行 2-3 秒的 `-∞ dB` 绝对物理静音，只留微观拟音呼吸，制造窒息戏剧张力；
  4. **【片尾平滑淡出与断点骤停】**：严格在最后 2 秒执行平滑淡出，遇集尾绝杀断点（Cliffhanger）瞬间随画面硬切黑屏骤停，严禁拖音拖尾。
* **输出规范（工业级纯净 JSON 数据契约呈现）**：
```json
{
  "episode_id": 1,
  "episode_title": "第 XX 集：[爆款标题]",
  "audio_specs": {
    "planned_duration_sec": 120.0,
    "target_sample_rate": "48kHz",
    "bit_depth": "24-bit",
    "broadcast_loudness_standard": "-23 LUFS",
    "inherited_leitmotif_id": "LEITMOTIF_02_GEARS_OF_THE_CITY",
    "inherited_leitmotif_name": "主题动机 2：齿轮之城 (准备钢琴+40Hz低频)"
  },
  "acoustic_traceability": {
    "stage_4_leitmotif_basis": "主音乐继承《齿轮之城》(准备钢琴卡硬币钝响 + 40Hz工矿低频持续震颤，BPM 86)；第 48 秒反转后混入《母亲的信》单音大提琴破损摩擦音变奏",
    "stage_1_worldview_basis": "北方重工业县城冷峻现实主义风格，100% 严禁大编制交响弦乐与廉价管乐煽情，保持克制冷感",
    "stage_7_timecode_basis": {
      "total_duration_sec": 120.0,
      "dialogue_ducking_ranges": [
        {"start": "00:00:03,500", "end": "00:00:45,000", "attenuation_db": -14.0}
      ]
    },
    "stage_5_dramatic_cues": {
      "hook_impact_timecode": "00:00:00,000 (挑开硬蜡触发开场突发重击 Braam Hit)",
      "micro_twist_silence_timecode": "00:00:45,000 --> 00:00:48,000 (翻出带血日记撕页触发 3.0 秒绝对断崖静音 -inf dB)",
      "cliffhanger_drop_timecode": "00:01:58,000 --> 00:02:00,000 (铁管砸向镜头触发重低音下潜 Sub-drop 随黑屏骤停)"
    }
  },
  "bgm_generation": {
    "model_target": "Suno v3.5 / Udio / 本地音乐大模型",
    "duration_sec": 120,
    "tempo_bpm": 86,
    "musical_key": "D minor",
    "full_master_prompt": "[Genre & Style]: Dark cinematic industrial suspense drone, gritty northern realism, no melodic orchestra, no cheap uplifting brass. [Technical Specs]: Exact duration: 120 seconds, Tempo: 86 BPM, Key: D minor, Wide dynamic range, professional film score mix, pristine sub-bass response. [Instrumentation]: Prepared piano with metallic clangs on strings, solo acoustic cello playing sul ponticello with harsh bow friction, continuous 40Hz industrial drone rumble, rhythmic mechanical tick-tock clock pulse, analog tape hiss. [Structured Timeline]: [00:00-00:03]: Sudden explosive Braam impact hit on first beat, immediately decaying into dark ambient low-end drone; [00:03-00:45]: Sparse low-end drone at -20dB, distant clock tick-tock rhythm, cold muted atmosphere allowing dialogue to breathe; [00:45-00:48]: [CRITICAL DROP]: Complete sudden drop to absolute silence (-inf dB), sharp audio cutoff on plot reveal, leaving room for raw foley gasp; [00:48-01:40]: Re-entry of distressed solo cello melody, rising metallic tension, accelerating heartbeat sub-bass building towards climax; [01:40-01:58]: Heavy accelerating industrial pulse, rising dissonant cluster chords; [01:58-02:00]: Massive cliffhanger sub-drop thud, cutting off abruptly into total silence on the final second with zero reverb tail."
  },
  "mastering_schedule": [
    {
      "timecode_range": "00:00:00,000 --> 00:00:03,500",
      "dramatic_state": "前3秒抓手动作 (开场刺破蜡封)",
      "target_bgm_volume_db": -12.0,
      "speech_ducking_active": false,
      "audio_action_notes": "开场突发重击点 (Braam Hit)，迅速收敛为低频底噪"
    },
    {
      "timecode_range": "00:00:03,500 --> 00:00:45,000",
      "dramatic_state": "试探对白潜流 (林晚与老郑对质)",
      "target_bgm_volume_db": -20.0,
      "speech_ducking_active": true,
      "audio_action_notes": "开启智能侧链避让 (-14dB 衰减)，40Hz 低频持续潜伏，不抢人声"
    },
    {
      "timecode_range": "00:00:45,000 --> 00:00:48,000",
      "dramatic_state": "第45秒核心微反转 (翻出带血日记撕页)",
      "target_bgm_volume_db": -999.0,
      "speech_ducking_active": false,
      "audio_action_notes": "【断崖式主观静音 3.0 秒 (-inf dB)】彻底切除音乐，留出倒吸凉气拟音"
    },
    {
      "timecode_range": "00:00:48,000 --> 00:01:58,000",
      "dramatic_state": "矛盾全面撕裂爆发 (激烈争吵对攻)",
      "target_bgm_volume_db": -14.0,
      "speech_ducking_active": true,
      "audio_action_notes": "单音大提琴破损摩擦音加速爬坡，打击乐逐渐加密"
    },
    {
      "timecode_range": "00:01:58,000 --> 00:02:00,000",
      "dramatic_state": "集尾绝杀断点 (铁管砸向镜头)",
      "target_bgm_volume_db": -8.0,
      "speech_ducking_active": false,
      "audio_action_notes": "重低音下潜 (Sub-drop)，动作砸下瞬间硬切黑屏骤停，无拖音拖尾"
    }
  ],
  "nle_mixing_guidelines": {
    "track_a1_dialogue": "音量基准 0.0 dB (人声响度 -23 LUFS)，开启轻度降噪与人声清晰度增强",
    "track_a2_foley": "衣物摩擦、水渍、金属碰撞声统一增益 +2.0dB ~ +3.0dB 强化电影质感",
    "track_a3_bgm": "导入本阶段生成之定制 BGM，挂载 Audio Ducking 侧链至 A1 轨 (衰减值 -14dB)；在 00:45-00:48 切断做 3 秒静音；在最后 2 秒设置平滑淡出并随断点硬切",
    "track_v1_v2_video_subtitles": "导入阶段 7 导出的标准 ep_XX.srt，应用短剧爆款样式 (黄色加粗、黑色描边、底部边距 120 像素避让操作栏)"
  },
  "audit_report": {
    "blue_team_compliance": {
      "four_bases_traced": true,
      "loudness_standard_met": "-23 LUFS",
      "full_prompt_valid": true,
      "schedule_timecode_aligned": true
    },
    "red_team_criticism": {
      "overpowering_risk": "BGM 在对白区间已强制降至 -20dB，且配器采用单音乐器与低频嗡鸣，绝不遮蔽耳语台词",
      "contrast_sharpness": "第 45 秒微反转处 3 秒绝对断崖静音前后无拖沓过渡，听觉反差极其锋利",
      "cutoff_cleanliness": "集尾绝杀断点最后 1 秒 Sub-drop 下潜重音随画面黑屏硬切，零拖尾泄气"
    },
    "verdict": "GREEN_APPROVED"
  }
}
```

* **🛑 阶段 8 单集正式结项门控**：
  完成第 XX 集音频工程与混音调度 JSON 数据包审查后：
  - 若需微调分贝调度或生乐提示词，就地修改 JSON 字段；
  - 若确认无误：
    * **【若 XX < 全季总集数】**：请回复“第 XX 集正式结项，进入第 XX+1 集”，管线将自动封装【集尾物理快照】，进入【第 XX+1 集阶段 6：按需资产准备】（文学剧本已定稿，无需再写，直接开启下一集资产准备）；
    * **【若 XX == 全季总集数】**：请回复“全季视听工程圆满结项”，全季短剧两程九阶全流程正式交付！