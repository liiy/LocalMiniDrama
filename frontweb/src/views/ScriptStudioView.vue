<template>
  <div class="script-studio-view" :class="{ 'theme-dark': isDark }">
    <!-- 1. 顶部全局导航栏 -->
    <header class="studio-header">
      <div class="header-left">
        <!-- 系统 Logo -->
        <div class="logo-box" @click="router.push('/')">
          <div class="logo-icon">L</div>
          <div class="logo-text">
            <span class="logo-main">本地短剧助手</span>
            <span class="logo-sub">LOCALMINIDRAMA</span>
          </div>
        </div>

        <!-- 剧名与版本下拉 -->
        <div class="drama-dropdown-wrap">
          <el-dropdown trigger="click" @command="onDramaChange">
            <span class="drama-selector-btn">
              <el-icon class="folder-icon"><FolderOpened /></el-icon>
              <span class="drama-title-text">{{ drama?.title || '未命名短剧' }}</span>
              <el-tag size="small" effect="plain" class="version-tag">
                v{{ drama?.version_cursor ? (drama.version_cursor + '.0') : '1.0' }}
              </el-tag>
              <el-icon class="arrow-icon"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="d in allDramas" :key="d.id" :command="d.id">
                  {{ d.title || '未命名短剧' }} (ID: {{ d.id }})
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <!-- 顶部右侧快捷模式与工具 -->
      <div class="header-right">
        <el-button class="nav-btn" @click="goCanvasMode">
          <el-icon><Grid /></el-icon>画布模式
        </el-button>
        <el-button class="nav-btn" @click="openWorkflowDrawer">
          <el-icon><Operation /></el-icon>工作流
        </el-button>
        <el-button class="nav-btn" @click="toggleTheme">
          <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
          {{ isDark ? '浅色' : '暗色' }}
        </el-button>
        <el-button class="nav-btn" @click="showAiConfigDialog = true">
          <el-icon><Setting /></el-icon>AI配置
        </el-button>
        <div class="user-avatar" title="编剧创作工作台">编</div>
      </div>
    </header>

    <!-- 2. 二级状态与控制栏 -->
    <div class="studio-subbar">
      <div class="subbar-left">
        <el-button link class="back-btn" @click="router.push(`/drama/${dramaId}`)">
          ‹ 返回剧集
        </el-button>
        <div class="current-ep-title">
          {{ currentEpisodeTitleDisplay }}
        </div>
        <el-tag v-if="currentEpisodeTag" size="small" type="primary" effect="light" class="ep-tag">
          {{ currentEpisodeTag }}
        </el-tag>
      </div>

      <div class="subbar-right">
        <el-button-group class="view-mode-group">
          <el-button :type="workbenchMode === 'create' ? 'primary' : ''" size="small" @click="workbenchMode = 'create'">创作剧本</el-button>
          <el-button :type="workbenchMode === 'select' ? 'primary' : ''" size="small" @click="workbenchMode = 'select'">选择剧本</el-button>
        </el-button-group>

        <div class="meta-pill">
          进度 <strong class="meta-val">{{ generatedCount }}</strong> / {{ totalCount }} 集
        </div>
        <div class="meta-pill">
          并发 <strong class="meta-val">2~3</strong> 集/批 <span class="meta-sub">Send API</span>
        </div>

        <el-button
          class="action-btn-highlight"
          :class="{ 'is-active': activeTab === 'story_input' }"
          @click="activeTab = 'story_input'"
        >
          <span class="btn-sparkle">✨</span> 故事生成
        </el-button>
        <el-button class="action-btn-normal" @click="onSaveCurrent">
          保存当前集
        </el-button>
        <el-button
          type="primary"
          class="action-btn-primary"
          :loading="locking"
          @click="onFinalizeAndBridge"
        >
          <el-icon><Lock /></el-icon> 确认定稿并转入视听制作
        </el-button>
      </div>
    </div>

    <!-- 3. 主体工作区（左侧双轨侧边栏 + 右侧内容面板） -->
    <div class="studio-body">
      <!-- 左侧主侧边栏 -->
      <aside class="studio-sidebar">
        <!-- 阶段 0：项目启动 -->
        <div class="nav-section-title">项目启动</div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'story_input' }"
          @click="activeTab = 'story_input'"
        >
          <div class="item-icon-box purple">
            <span class="sparkle-mini">✨</span>
          </div>
          <span class="item-label">故事生成</span>
          <span class="item-badge">{{ generatedCount }}/{{ totalCount }}</span>
        </div>

        <!-- 剧本创作工坊 (五阶段) -->
        <div class="nav-section-title">剧本创作工坊</div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage1_concept', done: stagePassed('stage1') }"
          @click="activeTab = 'stage1_concept'"
        >
          <div class="item-icon-box" :class="stagePassed('stage1') ? 'green' : 'num'">
            <el-icon v-if="stagePassed('stage1')"><Check /></el-icon>
            <span v-else>1</span>
          </div>
          <span class="item-label">创意立项</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage2_bible', done: stagePassed('stage2') }"
          @click="activeTab = 'stage2_bible'"
        >
          <div class="item-icon-box" :class="stagePassed('stage2') ? 'green' : 'num'">
            <el-icon v-if="stagePassed('stage2')"><Check /></el-icon>
            <span v-else>2</span>
          </div>
          <span class="item-label">故事圣经</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage3_outline', done: stagePassed('stage3') }"
          @click="activeTab = 'stage3_outline'"
        >
          <div class="item-icon-box" :class="stagePassed('stage3') ? 'green' : 'num'">
            <el-icon v-if="stagePassed('stage3')"><Check /></el-icon>
            <span v-else>3</span>
          </div>
          <span class="item-label">三级大纲</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage4_script', done: stagePassed('stage4') }"
          @click="activeTab = 'stage4_script'"
        >
          <div class="item-icon-box" :class="stagePassed('stage4') ? 'green' : 'num'">
            <el-icon v-if="stagePassed('stage4')"><Check /></el-icon>
            <span v-else>4</span>
          </div>
          <span class="item-label">故事剧本</span>
          <span v-if="stagePassed('stage4')" class="item-score-badge">{{ avgScore }}分</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage5_finalize', done: stagePassed('stage5') }"
          @click="activeTab = 'stage5_finalize'"
        >
          <div class="item-icon-box" :class="stagePassed('stage5') ? 'green' : 'num'">
            <el-icon v-if="stagePassed('stage5')"><Check /></el-icon>
            <span v-else>5</span>
          </div>
          <span class="item-label">复盘定稿</span>
        </div>

        <!-- Bridge 定稿契约卡片 -->
        <div class="bridge-contract-card" :class="{ locked: drama?.lock_status === 1 }">
          <div class="bridge-lock-icon">
            <el-icon><Lock /></el-icon>
          </div>
          <div class="bridge-info">
            <div class="bridge-title">定稿契约 Bridge</div>
            <div class="bridge-desc">{{ drama?.lock_status === 1 ? '剧本已锁定，实体已解析' : '定稿后自动解析分镜与实体' }}</div>
          </div>
        </div>

        <!-- 视听制作画布 (下游资产) -->
        <div class="nav-section-title">视听制作画布</div>
        <div class="nav-tree-item" @click="goToCanvasSection('characters')">
          <div class="item-icon-box num">6</div>
          <span class="item-label">角色</span>
          <span class="item-count-box">{{ characterCount }}</span>
        </div>
        <div class="nav-tree-item" @click="goToCanvasSection('props')">
          <div class="item-icon-box num">7</div>
          <span class="item-label">道具</span>
          <span class="item-count-box">{{ propCount }}</span>
        </div>
        <div class="nav-tree-item" @click="goToCanvasSection('scenes')">
          <div class="item-icon-box num">8</div>
          <span class="item-label">场景</span>
          <span class="item-count-box">{{ sceneCount }}</span>
        </div>
        <div class="nav-tree-item" @click="goToCanvasSection('storyboards')">
          <div class="item-icon-box num">9</div>
          <span class="item-label">分镜脚本</span>
          <span class="item-count-box">{{ storyboardCount }}</span>
        </div>
        <div class="nav-tree-item" @click="goToCanvasSection('video')">
          <div class="item-icon-box num">10</div>
          <span class="item-label">视频合成</span>
        </div>

        <!-- 底部快捷操作 -->
        <div class="sidebar-bottom-actions">
          <el-button type="primary" class="btn-batch-concurrent" @click="activeTab = 'story_input'">
            ⚡ 批次并发加速生成
          </el-button>
        </div>
      </aside>

      <!-- 右侧主内容区域 -->
      <main class="studio-main-panel">
        <!-- 阶段 0：故事生成 / 全剧生产管线起点 -->
        <div v-show="activeTab === 'story_input'" class="pipeline-stage-view">
          <!-- 上方五阶段横向管道指引卡片 -->
          <div class="pipeline-guide-card">
            <div class="guide-header">
              <div class="guide-title-box">
                <span class="stage-num-badge">0</span>
                <span class="stage-name-text">故事生成 · 全剧生产管线起点</span>
                <span class="stage-tag cold">冷启动</span>
              </div>
              <div class="guide-stats">
                本项目已生成 <strong>{{ generatedCount }} / {{ totalCount }}</strong> 集
              </div>
            </div>

            <!-- 横向 5 步进度流 -->
            <div class="horizontal-steps-bar">
              <div class="h-step-item active">
                <div class="step-card">
                  <div class="step-top">
                    <span class="step-icon">✨</span>
                    <span class="step-title">故事生成</span>
                  </div>
                  <div class="step-sub">输入已完成</div>
                </div>
              </div>
              <div class="h-step-arrow">›</div>

              <div class="h-step-item" :class="{ done: stagePassed('stage1') }">
                <div class="step-card">
                  <div class="step-top">
                    <el-icon v-if="stagePassed('stage1')" class="step-check"><Check /></el-icon>
                    <span v-else class="step-num">1</span>
                    <span class="step-title">创意立项</span>
                  </div>
                  <div class="step-sub">HITL-1 已通过</div>
                </div>
              </div>
              <div class="h-step-arrow">›</div>

              <div class="h-step-item" :class="{ done: stagePassed('stage2') }">
                <div class="step-card">
                  <div class="step-top">
                    <el-icon v-if="stagePassed('stage2')" class="step-check"><Check /></el-icon>
                    <span v-else class="step-num">2</span>
                    <span class="step-title">故事圣经</span>
                  </div>
                  <div class="step-sub">HITL-2 已通过</div>
                </div>
              </div>
              <div class="h-step-arrow">›</div>

              <div class="h-step-item" :class="{ done: stagePassed('stage3') }">
                <div class="step-card">
                  <div class="step-top">
                    <el-icon v-if="stagePassed('stage3')" class="step-check"><Check /></el-icon>
                    <span v-else class="step-num">3</span>
                    <span class="step-title">三级大纲</span>
                  </div>
                  <div class="step-sub">HITL-3 已通过</div>
                </div>
              </div>
              <div class="h-step-arrow">›</div>

              <div class="h-step-item" :class="{ done: stagePassed('stage4') }">
                <div class="step-card">
                  <div class="step-top">
                    <el-icon v-if="stagePassed('stage4')" class="step-check"><Check /></el-icon>
                    <span v-else class="step-num">4</span>
                    <span class="step-title">分集正文</span>
                  </div>
                  <div class="step-sub">已完成</div>
                </div>
              </div>
              <div class="h-step-arrow">›</div>

              <div class="h-step-item" :class="{ done: stagePassed('stage5') }">
                <div class="step-card">
                  <div class="step-top">
                    <el-icon v-if="stagePassed('stage5')" class="step-check"><Check /></el-icon>
                    <span v-else class="step-num">5</span>
                    <span class="step-title">复盘定稿</span>
                  </div>
                  <div class="step-sub">{{ stagePassed('stage5') ? '已定稿锁定' : '等待上游' }}</div>
                </div>
              </div>
            </div>

            <!-- 说明文本 -->
            <p class="guide-desc-text">
              在此输入一句话高概念或完整梗概（也可导入已有小说），系统将自动推进后续五阶段：先产出高概念方案交你审批，通过后再依次展开故事圣经、三级大纲与分集正文。<strong>生成前无需先做立项</strong>——立项结果由本环节产出。
            </p>
          </div>

          <!-- 故事生成核心输入表单卡片 -->
          <div class="story-form-card">
            <div class="form-card-header">
              <div class="form-title-left">
                <span class="title-badge-purple">生</span>
                <span class="title-main-text">故事生成</span>
                <span class="title-sub-text">输入故事梗概或从小说导入，一键生成全剧分集剧本</span>
              </div>
              <el-tag size="small" type="primary" effect="light" class="engine-tag">
                LangGraph 五阶段
              </el-tag>
            </div>

            <!-- 核心 Prompt / 梗概多行文本框 -->
            <div class="textarea-wrap">
              <el-input
                v-model="storyPrompt"
                type="textarea"
                :rows="6"
                placeholder="例如：记者林晚在母亲苏秀兰头七当晚，收到一封母亲生前寄给自己的信——七封信的最后一封，写着「囡囡，别查周家」。她顺着信里的线索回到老宅，却发现母亲的死，和二十年前周氏工厂那场被定为意外的火灾，牵着同一根线。刑警周行找上门来，他说他母亲也死在那场火里。"
                class="story-textarea"
              />
            </div>

            <!-- 题材 Tag 组 -->
            <div class="form-row">
              <span class="row-label">题材</span>
              <div class="tags-group">
                <span
                  v-for="item in genreOptions"
                  :key="item"
                  class="select-tag-pill"
                  :class="{ active: selectedGenre === item }"
                  @click="selectedGenre = item"
                >
                  {{ item }}
                </span>
              </div>
            </div>

            <!-- 类型 Tag 组 -->
            <div class="form-row">
              <span class="row-label">类型</span>
              <div class="tags-group">
                <span
                  v-for="item in typeOptions"
                  :key="item"
                  class="select-tag-pill"
                  :class="{ active: selectedType === item }"
                  @click="selectedType = item"
                >
                  {{ item }}
                </span>
              </div>
            </div>

            <!-- 集数 / 单集时长 / 付费卡点 -->
            <div class="form-row-inline">
              <div class="inline-item">
                <span class="row-label">集数</span>
                <div class="stepper-box">
                  <button class="step-btn" @click="changeEpisodes(-5)">-</button>
                  <span class="step-val">{{ episodeCount }}</span>
                  <button class="step-btn" @click="changeEpisodes(5)">+</button>
                </div>
              </div>

              <div class="inline-item">
                <span class="row-label">单集时长</span>
                <el-select v-model="episodeDuration" style="width: 100px" size="small">
                  <el-option label="60 秒" value="60s" />
                  <el-option label="90 秒" value="90s" />
                  <el-option label="120 秒" value="120s" />
                </el-select>
              </div>

              <div class="inline-item">
                <span class="row-label">付费卡点</span>
                <el-input v-model="paywallEpisodes" placeholder="10,15,20" style="width: 130px" size="small" />
              </div>
            </div>

            <!-- 并发生成策略 -->
            <div class="form-row">
              <span class="row-label">并发</span>
              <div class="tags-group">
                <span
                  v-for="c in concurrencyOptions"
                  :key="c.val"
                  class="select-tag-pill"
                  :class="{ active: selectedConcurrency === c.val }"
                  @click="selectedConcurrency = c.val"
                >
                  {{ c.label }}
                </span>
                <span class="concurrency-hint">
                  受控并发可提速约 300%（80 集 ≈ 8-10 分钟）
                </span>
              </div>
            </div>

            <!-- 人工审核模式 (HITL) 控制面板 -->
            <div class="hitl-control-panel">
              <div class="hitl-header">
                <div class="hitl-title-left">
                  <span class="hitl-avatar">🧔</span>
                  <span class="hitl-title">人工审核模式</span>
                  <span class="hitl-sub">每阶段生成后暂停，等待你审批才继续</span>
                </div>
                <div class="hitl-switch-box">
                  <span class="switch-label">{{ isHitlEnabled ? '开启' : '关闭' }}</span>
                  <el-switch v-model="isHitlEnabled" active-color="#8b5cf6" />
                </div>
              </div>

              <div class="hitl-options-row">
                <div
                  class="hitl-option-card"
                  :class="{ active: hitlStrategy === 'strict' }"
                  @click="hitlStrategy = 'strict'"
                >
                  <div class="opt-title">严格审核</div>
                  <div class="opt-desc">每阶段都审批</div>
                </div>
                <div
                  class="hitl-option-card"
                  :class="{ active: hitlStrategy === 'key_nodes' }"
                  @click="hitlStrategy = 'key_nodes'"
                >
                  <div class="opt-title">关键节点</div>
                  <div class="opt-desc">仅立项 + 定稿</div>
                </div>
                <div
                  class="hitl-option-card"
                  :class="{ active: hitlStrategy === 'auto' }"
                  @click="hitlStrategy = 'auto'"
                >
                  <div class="opt-title">全自动</div>
                  <div class="opt-desc">无人值守</div>
                </div>
              </div>
            </div>

            <!-- 底部操作按钮群 -->
            <div class="form-footer-actions">
              <div class="footer-left-btns">
                <el-button
                  v-if="isPipelinePaused"
                  type="success"
                  class="btn-resume-flow"
                  :loading="resuming"
                  @click="onResumePipeline"
                >
                  ▶ 继续推进下一阶段 (Resume)
                </el-button>
                <el-button v-else class="btn-step-next" @click="onContinueNextBatch">
                  ⏩ 继续生成下一批
                </el-button>
                <el-button class="btn-import-novel" @click="showNovelImportDialog = true">
                  <el-icon><DocumentAdd /></el-icon> 导入小说
                </el-button>
              </div>

              <div class="footer-right-btns">
                <el-button
                  type="primary"
                  class="btn-main-generate"
                  :loading="pipelineRunning"
                  @click="onStartPipeline"
                >
                  <span class="sparkle">✨</span> 生成剧本
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- 阶段 1：创意立项展示 (严格还原 UI 设计) -->
        <div v-show="activeTab === 'stage1_concept'" class="stage-content-view stage1-full-view">
          <!-- 顶部标题栏与 HITL 状态标签 -->
          <div class="stage1-top-header">
            <div class="header-left-title">
              <h2 class="stage1-main-title">1. 创意立项与高概念</h2>
            </div>
            <div class="header-right-tag">
              <span class="hitl-tag-pill">已通过 HITL-1</span>
            </div>
          </div>

          <!-- 审批通过状态横幅卡片 -->
          <div class="hitl-banner-card">
            <div class="banner-icon">
              <el-icon><Check /></el-icon>
            </div>
            <div class="banner-body">
              <div class="banner-title">已通过 HITL-1 审批</div>
              <div class="banner-desc">内容已锁定为下游输入；如需修改，请直接编辑下方字段 —— 保存后将自动标记下游失效。</div>
            </div>
            <div class="banner-actions">
              <el-button v-if="!isEditingConcept" size="small" class="btn-banner-edit" @click="startEditConcept">
                ✏ 手动修改
              </el-button>
              <el-button v-else type="primary" size="small" :loading="savingConcept" class="btn-banner-save" @click="saveConcept">
                💾 保存修改
              </el-button>
              <el-button size="small" class="btn-banner-regen" :loading="regeneratingConcept" @click="onRegenerateConcept">
                🔄 重新生成
              </el-button>
            </div>
          </div>

          <!-- 1. 一句话核心钩子 (One-Sentence Hook) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">1</span>
              <span class="sec-title">一句话核心钩子</span>
              <span class="sec-en">One-Sentence Hook</span>
            </div>
            <div class="hook-content-card">
              <!-- 大字引用文本 -->
              <div v-if="!isEditingConcept" class="hook-quote-text">
                “ {{ conceptData.one_sentence_hook }} ”
              </div>
              <el-input
                v-else
                v-model="conceptData.one_sentence_hook"
                type="textarea"
                :rows="2"
                placeholder="请输入一句话核心钩子"
                class="edit-hook-input"
              />

              <!-- AI 钩子解析 -->
              <div class="hook-ai-analysis">
                <span class="ai-robot-icon">🤖</span>
                <strong>AI 钩子解析：</strong>
                <span v-if="!isEditingConcept">{{ conceptData.hook_analysis.text }}</span>
                <el-input v-else v-model="conceptData.hook_analysis.text" size="small" style="margin-top: 6px" />
              </div>

              <!-- 4 列指标卡片 -->
              <div class="hook-metrics-grid">
                <div class="metric-card">
                  <div class="metric-label">3秒完播预估</div>
                  <div class="metric-val green">{{ conceptData.hook_analysis.play_rate_3s }}</div>
                </div>
                <div class="metric-card">
                  <div class="metric-label">悬念强度</div>
                  <div class="metric-val green">{{ conceptData.hook_analysis.suspense_score }}</div>
                </div>
                <div class="metric-card">
                  <div class="metric-label">情绪浓度</div>
                  <div class="metric-val green">{{ conceptData.hook_analysis.emotion_score }}</div>
                </div>
                <div class="metric-card">
                  <div class="metric-label">信息熵</div>
                  <div class="metric-val orange">{{ conceptData.hook_analysis.info_entropy }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 2. 全书总故事大纲 (Full Story Summary) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">2</span>
              <span class="sec-title">全书总故事大纲</span>
              <span class="sec-en">Full Story Summary</span>
            </div>

            <!-- 四幕网格 (2x2) -->
            <div class="four-acts-grid">
              <!-- 起因 -->
              <div class="act-card">
                <div class="act-card-head">
                  <div class="act-title-box">
                    <span class="act-dot blue"></span>
                    <strong class="act-name">起因</strong>
                  </div>
                  <span class="act-range">{{ conceptData.four_acts.cause.ep_range }}</span>
                </div>
                <div v-if="!isEditingConcept" class="act-card-body">
                  {{ conceptData.four_acts.cause.content }}
                </div>
                <el-input v-else v-model="conceptData.four_acts.cause.content" type="textarea" :rows="4" />
              </div>

              <!-- 发展 -->
              <div class="act-card">
                <div class="act-card-head">
                  <div class="act-title-box">
                    <span class="act-dot purple"></span>
                    <strong class="act-name">发展</strong>
                  </div>
                  <span class="act-range">{{ conceptData.four_acts.development.ep_range }}</span>
                </div>
                <div v-if="!isEditingConcept" class="act-card-body">
                  {{ conceptData.four_acts.development.content }}
                </div>
                <el-input v-else v-model="conceptData.four_acts.development.content" type="textarea" :rows="4" />
              </div>

              <!-- 高潮 -->
              <div class="act-card">
                <div class="act-card-head">
                  <div class="act-title-box">
                    <span class="act-dot orange"></span>
                    <strong class="act-name">高潮</strong>
                  </div>
                  <span class="act-range">{{ conceptData.four_acts.climax.ep_range }}</span>
                </div>
                <div v-if="!isEditingConcept" class="act-card-body">
                  {{ conceptData.four_acts.climax.content }}
                </div>
                <el-input v-else v-model="conceptData.four_acts.climax.content" type="textarea" :rows="4" />
              </div>

              <!-- 终局 -->
              <div class="act-card">
                <div class="act-card-head">
                  <div class="act-title-box">
                    <span class="act-dot green"></span>
                    <strong class="act-name">终局</strong>
                  </div>
                  <span class="act-range">{{ conceptData.four_acts.ending.ep_range }}</span>
                </div>
                <div v-if="!isEditingConcept" class="act-card-body">
                  {{ conceptData.four_acts.ending.content }}
                </div>
                <el-input v-else v-model="conceptData.four_acts.ending.content" type="textarea" :rows="4" />
              </div>
            </div>

            <!-- 核心伏笔池 -->
            <div class="clue-pool-card">
              <div class="clue-pool-head">
                <div class="clue-head-left">
                  <span class="clue-icon">🪆</span>
                  <strong>核心伏笔池</strong>
                  <span class="clue-count-sub">{{ conceptData.clues.length }} 条 · 已排布回收点</span>
                </div>
                <el-button v-if="isEditingConcept" size="small" type="primary" plain @click="addClueItem">
                  + 新增伏笔
                </el-button>
              </div>

              <div class="clue-list-box">
                <div v-for="(clue, idx) in conceptData.clues" :key="clue.id || idx" class="clue-item-row">
                  <span class="clue-code">{{ clue.id || `CLUE_${String(idx+1).padStart(3, '0')}` }}</span>
                  <span v-if="!isEditingConcept" class="clue-name">{{ clue.name }}</span>
                  <el-input v-else v-model="clue.name" size="small" style="max-width: 240px" />
                  
                  <el-tag size="small" :type="clue.tag === '核心' ? 'primary' : clue.tag === '长线' ? 'info' : 'warning'">
                    {{ clue.tag }}
                  </el-tag>
                  
                  <span v-if="!isEditingConcept" class="clue-recycle-text">
                    {{ clue.buried_ep }} 埋 / {{ clue.resolved_ep }} 回收
                  </span>
                  <div v-else class="clue-edit-eps">
                    <el-input v-model="clue.buried_ep" placeholder="埋点" size="small" style="width: 70px" />
                    <span>/</span>
                    <el-input v-model="clue.resolved_ep" placeholder="回收" size="small" style="width: 70px" />
                    <el-button type="danger" link size="small" @click="removeClueItem(idx)">删除</el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 3. 商业与受众分析 (Business & Audience) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">3</span>
              <span class="sec-title">商业与受众分析</span>
              <span class="sec-en">Business & Audience</span>
            </div>

            <div class="biz-audience-grid">
              <!-- 左侧：目标受众画像 -->
              <div class="biz-subcard">
                <div class="biz-subcard-title">
                  <span class="biz-sub-icon">🎯</span>
                  <strong>目标受众画像</strong>
                </div>
                <div v-if="!isEditingConcept" class="biz-desc-text">
                  {{ conceptData.audience_analysis.target_audience }}
                </div>
                <el-input v-else v-model="conceptData.audience_analysis.target_audience" type="textarea" :rows="4" />
              </div>

              <!-- 右侧：付费转化驱动力 -->
              <div class="biz-subcard">
                <div class="biz-subcard-title">
                  <span class="biz-sub-icon">💰</span>
                  <strong>付费转化驱动力</strong>
                </div>
                <div class="drivers-energy-list">
                  <div v-for="driver in conceptData.audience_analysis.paywall_drivers" :key="driver.name" class="driver-bar-item">
                    <span class="driver-name">{{ driver.name }}</span>
                    <div class="driver-bar-track">
                      <div class="driver-bar-fill" :style="{ width: `${driver.score}%` }"></div>
                    </div>
                    <span class="driver-score">{{ driver.score }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 付费卡点集数列表 -->
            <div class="paywall-nodes-card">
              <div class="paywall-nodes-title">
                <span class="paywall-icon">🔒</span>
                <strong>付费卡点集数列表</strong>
                <span class="paywall-sub">（决定付费墙位置）</span>
              </div>
              <div class="paywall-chips-row">
                <div v-for="(node, idx) in conceptData.audience_analysis.paywall_episodes" :key="idx" class="paywall-chip">
                  <strong class="chip-ep">第 {{ node.episode }} 集</strong>
                  <span class="chip-reason">{{ node.reason }}</span>
                  <el-icon v-if="isEditingConcept" class="chip-del" @click="removePaywallNode(idx)"><Close /></el-icon>
                </div>
                <el-button v-if="isEditingConcept" size="small" class="btn-add-paywall" @click="addPaywallNode">
                  + 添加卡点
                </el-button>
              </div>
            </div>

            <!-- 商业定位 -->
            <div class="commercial-pos-card">
              <div class="pos-title-row">
                <span class="pos-icon">📊</span>
                <strong>商业定位</strong>
              </div>
              <div v-if="!isEditingConcept" class="pos-desc-text">
                {{ conceptData.audience_analysis.commercial_positioning }}
              </div>
              <el-input v-else v-model="conceptData.audience_analysis.commercial_positioning" type="textarea" :rows="2" />
            </div>
          </div>

          <!-- 4. 情绪与节奏基调 (Emotion & Rhythm) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">4</span>
              <span class="sec-title">情绪与节奏基调</span>
              <span class="sec-en">Emotion & Rhythm</span>
            </div>

            <div class="emotion-rhythm-grid">
              <!-- 左侧：情绪曲线类型 -->
              <div class="emotion-left-card">
                <div class="card-inner-title">情绪曲线类型</div>
                <!-- SVG 波浪曲线图 -->
                <div class="curve-chart-box">
                  <svg viewBox="0 0 280 90" class="curve-svg" preserveAspectRatio="none">
                    <defs>
                      <linearGradient id="curveGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stop-color="#8b5cf6" stop-opacity="0.35" />
                        <stop offset="100%" stop-color="#8b5cf6" stop-opacity="0.0" />
                      </linearGradient>
                    </defs>
                    <path
                      d="M 10 75 Q 35 85, 60 70 T 110 50 T 160 38 T 210 25 T 260 15 L 260 85 L 10 85 Z"
                      fill="url(#curveGrad)"
                    />
                    <path
                      d="M 10 75 Q 35 85, 60 70 T 110 50 T 160 38 T 210 25 T 260 15"
                      fill="none"
                      stroke="#8b5cf6"
                      stroke-width="2.5"
                      stroke-linecap="round"
                    />
                  </svg>
                  <div class="curve-axis-labels">
                    <span>E01</span>
                    <span class="axis-center">集数 →</span>
                    <span>E{{ totalCount }}</span>
                  </div>
                </div>

                <!-- 曲线类型选项按钮 -->
                <div class="curve-tags-grid">
                  <button
                    v-for="opt in conceptData.emotion_rhythm.curve_options"
                    :key="opt"
                    type="button"
                    class="curve-tag-btn"
                    :class="{ active: conceptData.emotion_rhythm.selected_curve === opt }"
                    @click="conceptData.emotion_rhythm.selected_curve = opt"
                  >
                    {{ opt }}
                  </button>
                </div>
              </div>

              <!-- 右侧：视听节拍节奏规划 -->
              <div class="rhythm-right-card">
                <div class="card-inner-title">视听节拍节奏规划</div>
                <div class="rhythm-phases-list">
                  <div
                    v-for="phase in conceptData.emotion_rhythm.rhythm_phases"
                    :key="phase.ep_range"
                    class="rhythm-phase-item"
                  >
                    <span class="rhythm-range-tag">{{ phase.ep_range }}</span>
                    <strong class="rhythm-phase-name">{{ phase.title }}</strong>
                    <span class="rhythm-phase-desc">{{ phase.desc }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 阶段 2：故事圣经与世界观 (严格还原 UI 设计) -->
        <div v-show="activeTab === 'stage2_bible'" class="stage-content-view stage2-full-view">
          <!-- 顶部标题栏与 HITL 状态标签 -->
          <div class="stage-top-header">
            <div class="header-left-title">
              <h2 class="stage-main-title">2. 故事圣经与世界观</h2>
            </div>
            <div class="header-right-tag">
              <span class="hitl-tag-pill">已通过 HITL-2</span>
            </div>
          </div>

          <!-- 审批通过状态横幅卡片 -->
          <div class="hitl-banner-card">
            <div class="banner-icon">
              <el-icon><Check /></el-icon>
            </div>
            <div class="banner-body">
              <div class="banner-title">已通过 HITL-2 审批</div>
              <div class="banner-desc">故事圣经与人设库已构建完毕；如需修改，请点击“手动修改”或直接更新人物矩阵。</div>
            </div>
            <div class="banner-actions">
              <el-button v-if="!isEditingBible" size="small" class="btn-banner-edit" @click="startEditBible">
                ✏ 手动修改
              </el-button>
              <el-button v-else type="primary" size="small" :loading="savingBible" class="btn-banner-save" @click="saveBible">
                💾 保存修改
              </el-button>
              <el-button size="small" class="btn-banner-regen" :loading="regeneratingBible" @click="onRegenerateBible">
                🔄 重新生成
              </el-button>
            </div>
          </div>

          <!-- 1. 世界观与三大铁律 (Worldview & 3 Iron Rules) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">1</span>
              <span class="sec-title">世界观与三大铁律</span>
              <span class="sec-en">Worldview & 3 Iron Rules</span>
            </div>

            <!-- 三大铁律卡片 -->
            <div class="iron-rules-grid">
              <div v-for="(rule, rIdx) in bibleData.worldview.iron_rules" :key="rule.id || rIdx" class="iron-rule-card">
                <div class="rule-head">
                  <span class="rule-badge">{{ rule.id }}</span>
                  <strong class="rule-name">{{ rule.name }}</strong>
                </div>
                <div v-if="!isEditingBible" class="rule-desc">{{ rule.desc }}</div>
                <el-input v-else v-model="rule.desc" type="textarea" :rows="3" size="small" />
              </div>
            </div>

            <!-- 社会阶层与核心矛盾 -->
            <div class="worldview-sub-grid">
              <!-- 左：社会阶层分布 -->
              <div class="hierarchy-card">
                <div class="card-inner-title">三层社会阶层架构</div>
                <div class="hierarchy-list">
                  <div v-for="layer in bibleData.worldview.social_hierarchy.layers" :key="layer.name" class="hierarchy-item">
                    <div class="layer-header">
                      <strong class="layer-name">{{ layer.name }}</strong>
                      <span class="layer-pct" :style="{ color: layer.color }">{{ layer.percent }}%</span>
                    </div>
                    <div class="layer-track">
                      <div class="layer-fill" :style="{ width: `${layer.percent}%`, backgroundColor: layer.color }"></div>
                    </div>
                    <div class="layer-desc">{{ layer.desc }}</div>
                  </div>
                </div>
              </div>

              <!-- 右：核心矛盾 -->
              <div class="core-conflict-card">
                <div class="card-inner-title">
                  <span class="conflict-icon">⚡</span>
                  <strong>{{ bibleData.worldview.core_conflict.title }}</strong>
                </div>
                <div v-if="!isEditingBible" class="conflict-text">
                  {{ bibleData.worldview.core_conflict.desc }}
                </div>
                <el-input v-else v-model="bibleData.worldview.core_conflict.desc" type="textarea" :rows="5" />
              </div>
            </div>
          </div>

          <!-- 2. 九维人物小传 (9-Dimensional Character Bible) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">2</span>
              <span class="sec-title">九维人物小传</span>
              <span class="sec-en">9-Dimensional Character Bible</span>
            </div>

            <!-- 角色选择 Tabs -->
            <div class="char-tabs-bar">
              <button
                v-for="char in bibleData.characters"
                :key="char.name"
                type="button"
                class="char-tab-btn"
                :class="{ active: activeCharTab === char.name }"
                @click="activeCharTab = char.name"
              >
                <span class="char-avatar-mini">{{ char.avatar }}</span>
                <span class="char-tab-name">{{ char.name }}</span>
                <span class="char-tab-tag">{{ char.role_tag.split('·')[0].trim() }}</span>
              </button>
            </div>

            <!-- 选中的九维角色详情档案 -->
            <div v-if="currentChar" class="nine-dim-profile-card">
              <!-- 人物头部概要 -->
              <div class="profile-header-box">
                <div class="profile-avatar-box">
                  <span class="profile-avatar-emoji">{{ currentChar.avatar }}</span>
                </div>
                <div class="profile-info-box">
                  <div class="profile-name-row">
                    <strong class="profile-name">{{ currentChar.name }}</strong>
                    <el-tag size="small" :type="currentChar.role_type === 'protagonist' ? 'danger' : currentChar.role_type === 'antagonist' ? 'warning' : 'info'">
                      {{ currentChar.role_tag }}
                    </el-tag>
                    <span class="profile-seed">Seed: {{ currentChar.seed }}</span>
                  </div>
                  <div class="profile-summary-text">
                    <strong>视觉锚点：</strong>{{ currentChar.nine_dimensions.visual_anchor }}
                  </div>
                </div>
              </div>

              <!-- 9 维矩阵属性网格 -->
              <div class="nine-dim-grid">
                <div class="dim-field-card">
                  <div class="dim-label">① 身份与面具 (Mask)</div>
                  <div v-if="!isEditingBible" class="dim-val">{{ currentChar.nine_dimensions.mask }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.mask" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">② 本我 (True Self)</div>
                  <div v-if="!isEditingBible" class="dim-val">{{ currentChar.nine_dimensions.true_self }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.true_self" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">③ 视觉识别锚点 (Visual Anchor)</div>
                  <div v-if="!isEditingBible" class="dim-val highlight-green">{{ currentChar.nine_dimensions.visual_anchor }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.visual_anchor" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">④ 表面欲望 (Desire)</div>
                  <div v-if="!isEditingBible" class="dim-val">{{ currentChar.nine_dimensions.desire }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.desire" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">⑤ 核心缺陷 (Weakness)</div>
                  <div v-if="!isEditingBible" class="dim-val">{{ currentChar.nine_dimensions.weakness }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.weakness" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">⑥ 绝密底牌 (Secret)</div>
                  <div v-if="!isEditingBible" class="dim-val highlight-orange">{{ currentChar.nine_dimensions.secret }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.secret" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">⑦ 恐惧深渊 (Fear)</div>
                  <div v-if="!isEditingBible" class="dim-val">{{ currentChar.nine_dimensions.fear }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.fear" size="small" />
                </div>
                <div class="dim-field-card">
                  <div class="dim-label">⑧ 道德底线 (Moral Line)</div>
                  <div v-if="!isEditingBible" class="dim-val">{{ currentChar.nine_dimensions.moral_line }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.moral_line" size="small" />
                </div>
                <div class="dim-field-card dim-col-span-2">
                  <div class="dim-label">⑨ 终极人物弧光 (Character Arc)</div>
                  <div v-if="!isEditingBible" class="dim-val highlight-purple">{{ currentChar.nine_dimensions.arc }}</div>
                  <el-input v-else v-model="currentChar.nine_dimensions.arc" size="small" />
                </div>
              </div>
            </div>
          </div>

          <!-- 3. 人物关系网络图 (Dynamic Relationship Graph) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">3</span>
              <span class="sec-title">人物关系网络图（动态演进）</span>
              <span class="sec-en">Dynamic Relationship Graph</span>
            </div>

            <!-- 时间线刻度切换条 -->
            <div class="relation-timeline-box">
              <span class="timeline-hint">时间线刻度回放：</span>
              <div class="timeline-nodes-row">
                <button
                  v-for="epNode in bibleData.relationship_graph.timeline_nodes"
                  :key="epNode"
                  type="button"
                  class="timeline-ep-btn"
                  :class="{ active: currentRelationTimeEp === epNode }"
                  @click="currentRelationTimeEp = epNode"
                >
                  {{ epNode }}
                </button>
              </div>
            </div>

            <!-- 关系网呈现区域 -->
            <div class="relation-graph-container">
              <!-- 关系卡片网格 -->
              <div class="relation-cards-grid">
                <div
                  v-for="(rel, relIdx) in currentRelations"
                  :key="relIdx"
                  class="relation-item-card"
                  :class="rel.type"
                >
                  <div class="rel-header">
                    <span class="rel-entity from">{{ rel.from }}</span>
                    <span class="rel-arrow">⇄</span>
                    <span class="rel-entity to">{{ rel.to }}</span>
                  </div>
                  <div class="rel-tag-pill">{{ rel.label }}</div>
                  <div class="rel-desc-text">{{ rel.desc }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 4. 核心道具库 (Core Props & Prompt Extraction) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <div class="sec-head-left">
                <span class="sec-badge">4</span>
                <span class="sec-title">核心道具库</span>
                <span class="sec-en">Core Props & Prompt Extraction</span>
              </div>
              <div class="sec-head-right">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="extractingProps"
                  @click="onExtractProps"
                >
                  ✨ 一键从剧本正文抽取生图 Prompt
                </el-button>
              </div>
            </div>

            <!-- 道具卡片列表 -->
            <div class="props-list-grid">
              <div v-for="prop in bibleData.props_library.items" :key="prop.id" class="prop-item-card">
                <div class="prop-card-head">
                  <div class="prop-name-row">
                    <strong class="prop-name">{{ prop.name }}</strong>
                    <el-tag size="small" type="success">{{ prop.tag }}</el-tag>
                  </div>
                  <span class="prop-id">{{ prop.id }}</span>
                </div>
                <div class="prop-desc">{{ prop.desc }}</div>

                <!-- 正文片段引用 -->
                <div class="prop-fragments-box">
                  <div class="frag-title">📖 剧本正文片段引用：</div>
                  <div v-for="(frag, fIdx) in prop.fragments" :key="fIdx" class="frag-item">
                    <span class="frag-ep">{{ frag.ep }}</span>
                    <span class="frag-text">“{{ frag.text }}”</span>
                  </div>
                </div>

                <!-- 生图 Visual Prompt -->
                <div class="prop-prompt-box">
                  <div class="prompt-title">🎨 视听生图 Visual Prompt：</div>
                  <div v-if="!isEditingBible" class="prompt-content">{{ prop.visual_prompt }}</div>
                  <el-input v-else v-model="prop.visual_prompt" type="textarea" :rows="2" size="small" />
                </div>
              </div>
            </div>
          </div>

          <!-- 5. 声音与情绪配乐设计 (Sound & Emotion Bibles) -->
          <div class="concept-section-card">
            <div class="sec-head">
              <span class="sec-badge">5</span>
              <span class="sec-title">声音与情绪配乐设计</span>
              <span class="sec-en">Sound & Emotion Bibles</span>
            </div>

            <div class="music-overall-box">
              <div class="music-title-row">
                <span class="music-icon">🎵</span>
                <strong>整剧配乐风格规范</strong>
                <span class="music-bpm-badge">{{ bibleData.music_bible.bpm_rules }}</span>
              </div>
              <div v-if="!isEditingBible" class="music-style-text">{{ bibleData.music_bible.overall_style }}</div>
              <el-input v-else v-model="bibleData.music_bible.overall_style" type="textarea" :rows="2" />
            </div>

            <!-- 4 大核心动机卡片 -->
            <div class="motifs-grid">
              <div v-for="motif in bibleData.music_bible.motifs" :key="motif.id" class="motif-card">
                <div class="motif-head">
                  <span class="motif-dot" :style="{ backgroundColor: motif.color }"></span>
                  <strong class="motif-name">{{ motif.name }}</strong>
                  <span class="motif-bpm">{{ motif.bpm }}</span>
                </div>
                <div class="motif-field"><strong>乐器：</strong>{{ motif.instruments }}</div>
                <div class="motif-field"><strong>情绪：</strong>{{ motif.emotion }}</div>
                <div class="motif-field"><strong>覆盖集数：</strong>{{ motif.episodes }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 阶段 3：三级大纲工作台 (严格还原 UI 设计 + 顶部一级总纲 Sticky + 底部 HITL 控制栏 Sticky) -->
        <div v-show="activeTab === 'stage3_outline'" class="stage-content-view stage3-full-container">
          <!-- 顶部常驻固定区：一级大纲概览 (Sticky Top) -->
          <div class="stage3-sticky-top-header">
            <div class="stage3-top-summary-card">
              <div class="stage3-top-left">
                <div class="s3-badge-title">
                  <span class="s3-badge">1</span>
                  <strong class="s3-title-text">一级总纲概览 · 全剧核心骨架</strong>
                  <span class="s3-sub-hook">“ {{ conceptData.one_sentence_hook }} ”</span>
                </div>
                <div class="s3-four-acts-summary">
                  <span class="act-chip blue">起因: {{ conceptData.four_acts.cause.ep_range }}</span>
                  <span class="act-chip purple">发展: {{ conceptData.four_acts.development.ep_range }}</span>
                  <span class="act-chip orange">高潮: {{ conceptData.four_acts.climax.ep_range }}</span>
                  <span class="act-chip green">终局: {{ conceptData.four_acts.ending.ep_range }}</span>
                </div>
              </div>
              <div class="stage3-top-right">
                <el-button size="small" plain class="btn-jump-stage1" @click="activeTab = 'stage1_concept'">
                  前往修改一级大纲 ›
                </el-button>
              </div>
            </div>
          </div>

          <!-- 中部纵向滚动内容区 -->
          <div class="stage3-scrollable-body">
            <!-- 2. 二级四幕剧情大纲 (Four Acts Breakdown) -->
            <div class="concept-section-card">
              <div class="sec-head">
                <span class="sec-badge">2</span>
                <span class="sec-title">二级四幕剧情大纲</span>
                <span class="sec-en">Four Acts Breakdown (20 Eps / Act)</span>
              </div>

              <div class="two-level-acts-grid">
                <div v-for="act in outlineData.two_level_acts" :key="act.act_num" class="act-breakdown-card">
                  <div class="act-head-row">
                    <div class="act-name-box">
                      <span class="act-num-pill">第 {{ act.act_num }} 幕</span>
                      <strong class="act-title">{{ act.title }}</strong>
                    </div>
                    <span class="act-ep-range">{{ act.ep_range }} ({{ act.ep_count }})</span>
                  </div>

                  <div class="act-field-item">
                    <div class="f-label">🎯 阶段目标</div>
                    <div v-if="!isEditingOutline" class="f-val">{{ act.target }}</div>
                    <el-input v-else v-model="act.target" size="small" />
                  </div>

                  <div class="act-field-item">
                    <div class="f-label">⚔️ 主要冲突</div>
                    <div v-if="!isEditingOutline" class="f-val">{{ act.main_conflict }}</div>
                    <el-input v-else v-model="act.main_conflict" size="small" />
                  </div>

                  <div class="act-field-item">
                    <div class="f-label">🔍 核心悬念 / 线索</div>
                    <div v-if="!isEditingOutline" class="f-val highlight-blue">{{ act.clues }}</div>
                    <el-input v-else v-model="act.clues" size="small" />
                  </div>

                  <div class="act-bottom-emotion">
                    <span class="emo-label">转折点：{{ act.emotion_base }}</span>
                    <span class="emo-score">指数: {{ act.emotion_score }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 3. 三级分集微观节拍表 (Episode Beats Table) -->
            <div class="concept-section-card">
              <div class="sec-head">
                <div class="sec-head-left">
                  <span class="sec-badge">3</span>
                  <span class="sec-title">三级分集微观节拍</span>
                  <span class="sec-en">Episode Beats Table</span>
                </div>
                <div class="sec-head-right">
                  <el-button v-if="isEditingOutline" size="small" type="primary" plain @click="addBeatItem">
                    + 新增分集节拍
                  </el-button>
                </div>
              </div>

              <!-- 分集节拍表格 -->
              <div class="beats-table-wrapper">
                <table class="beats-data-table">
                  <thead>
                    <tr>
                      <th style="width: 70px">集数</th>
                      <th style="width: 140px">主场景</th>
                      <th style="width: 240px">核心动作</th>
                      <th style="width: 200px">反转 / 信息差</th>
                      <th>片尾断章钩子</th>
                      <th style="width: 120px">商业标签</th>
                      <th style="width: 80px">状态</th>
                      <th v-if="isEditingOutline" style="width: 60px">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(beat, bIdx) in outlineData.three_level_beats" :key="beat.episode_num || bIdx">
                      <td class="td-ep-num">E{{ String(beat.episode_num).padStart(2, '0') }}</td>
                      <td>
                        <span v-if="!isEditingOutline" class="scene-tag">{{ beat.main_scene }}</span>
                        <el-input v-else v-model="beat.main_scene" size="small" />
                      </td>
                      <td>
                        <span v-if="!isEditingOutline">{{ beat.core_action }}</span>
                        <el-input v-else v-model="beat.core_action" size="small" />
                      </td>
                      <td>
                        <span v-if="!isEditingOutline" :class="{ 'reversal-text': beat.reversal !== '—' }">{{ beat.reversal }}</span>
                        <el-input v-else v-model="beat.reversal" size="small" />
                      </td>
                      <td>
                        <span v-if="!isEditingOutline" class="cliffhanger-highlight">🔥 {{ beat.ending_cliffhanger }}</span>
                        <el-input v-else v-model="beat.ending_cliffhanger" size="small" />
                      </td>
                      <td>
                        <el-tag
                          size="small"
                          :type="beat.commercial_tag === '核心付费卡点' ? 'danger' : beat.commercial_tag === '情绪爆点' ? 'warning' : 'info'"
                        >
                          {{ beat.commercial_tag }}
                        </el-tag>
                      </td>
                      <td>
                        <span class="status-done-text">✓ 已生成</span>
                      </td>
                      <td v-if="isEditingOutline">
                        <el-button type="danger" link size="small" @click="removeBeatItem(bIdx)">删除</el-button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- 4. 主场景库降本占比分布 (Main Scenes Pool) -->
            <div class="concept-section-card">
              <div class="sec-head">
                <span class="sec-badge">4</span>
                <span class="sec-title">主场景库（降本与复用统计）</span>
                <span class="sec-en">Main Scenes Pool · 复用率 82%，降本约 35%</span>
              </div>

              <div class="scenes-pool-grid">
                <div v-for="sc in outlineData.main_scenes_pool" :key="sc.name" class="scene-pool-card">
                  <div class="sc-head">
                    <strong class="sc-name">{{ sc.name }}</strong>
                    <span class="sc-pct">{{ sc.percent }}</span>
                  </div>
                  <div class="sc-bar-track">
                    <div class="sc-bar-fill" :style="{ width: sc.percent }"></div>
                  </div>
                  <div class="sc-desc">{{ sc.desc }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 底部常驻固定区：HITL 人工干预控制栏 (Sticky Bottom) -->
          <div class="stage3-sticky-bottom-bar">
            <div class="hitl-bottom-content">
              <!-- 左侧质检指标 Chips -->
              <div class="hitl-chips-box">
                <div class="hitl-bar-title">
                  <el-icon class="hitl-ok-icon"><Check /></el-icon>
                  <strong>大纲工业化质检通过</strong>
                </div>
                <div class="hitl-metric-chips">
                  <div v-for="chk in outlineData.validation_checks" :key="chk.id" class="metric-chip-item">
                    <span class="chk-icon">✓</span>
                    <span class="chk-label">{{ chk.label }}</span>
                    <span class="chk-val">{{ chk.value }}</span>
                  </div>
                </div>
              </div>

              <!-- 右侧操作按钮组 -->
              <div class="hitl-actions-box">
                <el-button v-if="!isEditingOutline" size="default" class="btn-hitl-edit" @click="startEditOutline">
                  ✏ 手动修改
                </el-button>
                <el-button v-else type="primary" size="default" :loading="savingOutline" class="btn-hitl-save" @click="saveOutline">
                  💾 保存大纲
                </el-button>
                <el-button size="default" class="btn-hitl-regen" :loading="regeneratingOutline" @click="onRegenerateOutline">
                  🔄 重新生成大纲
                </el-button>
                <el-button size="default" class="btn-hitl-val" :loading="validatingOutline" @click="onValidateOutline">
                  🔍 重新校验
                </el-button>
                <el-button
                  type="success"
                  size="default"
                  :loading="resuming"
                  class="btn-hitl-confirm"
                  @click="confirmAndBatchGenerate"
                >
                  ✓ 确认大纲并批量生成正文
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- 阶段 4：故事剧本（高保真三栏工坊：左侧集数导航 + 中部 AST 四分块 + 右侧质检与连续性） -->
        <div v-show="activeTab === 'stage4_script'" class="stage-content-view stage4-full-workbench">
          <div class="stage4-studio-layout">
            <!-- 1. 左侧：集数导航（支持搜索、滚动、Hover展开操作、分镜与卡点展示） -->
            <aside class="stage4-episodes-nav-col">
              <div class="ep-nav-top-header">
                <div class="ep-nav-title-row">
                  <span class="ep-nav-title-text">集数导航</span>
                  <span class="ep-nav-total-badge">{{ totalCount }} 集</span>
                </div>
                <!-- 集名搜索过滤框 -->
                <div class="ep-nav-search-wrap">
                  <el-input
                    v-model="episodeSearchKeyword"
                    placeholder="搜索分集名 / 序号..."
                    clearable
                    size="small"
                    :prefix-icon="Search"
                    class="ep-search-input"
                  />
                </div>
              </div>

              <!-- 滚动列表区 -->
              <div class="ep-nav-scroll-list">
                <div
                  v-for="unit in filteredUnits"
                  :key="unit.unit_index"
                  class="ep-unit-group-block"
                >
                  <div class="ep-unit-header-row">
                    <span class="unit-name">{{ unit.title }}</span>
                    <span class="unit-paywall-tag">{{ unit.paywall_label }}</span>
                  </div>

                  <div class="ep-unit-items-list">
                    <div
                      v-for="ep in unit.episodes"
                      :key="ep.episode_number"
                      class="ep-list-item-row"
                      :class="{
                        active: currentEpisodeNumber === ep.episode_number,
                        generated: ep.generated,
                        'is-stale': ep.badge === 'Stale'
                      }"
                      @click="selectEpisode(ep.episode_number)"
                    >
                      <div class="ep-item-left-info">
                        <span class="ep-status-dot" :class="epDotClass(ep)" />
                        <span class="ep-number-text">{{ formatEpNum(ep.episode_number) }}</span>
                        <span class="ep-title-text" :title="ep.title">{{ ep.title }}</span>
                      </div>

                      <div class="ep-item-right-wrap">
                        <!-- 常态展示：评分/状态徽章/分镜数 -->
                        <div class="ep-normal-badges">
                          <span v-if="ep.score" class="ep-score-value">{{ ep.score }}</span>
                          <span v-else class="ep-score-empty">--</span>
                          <span
                            v-if="ep.badge"
                            class="ep-badge-pill"
                            :class="ep.badge === 'Stale' ? 'badge-stale' : 'badge-concurrent'"
                          >
                            {{ ep.badge }}
                          </span>
                        </div>

                        <!-- 鼠标悬浮 Hover 时向左平移露出的操作按钮组 -->
                        <div class="ep-hover-actions-group">
                          <el-tooltip content="重新生成本集" placement="top" :show-after="200">
                            <button
                              type="button"
                              class="ep-circle-act-btn"
                              :disabled="regeneratingEpisode"
                              @click.stop="onRegenerateSingleEp(ep.episode_number)"
                            >
                              <el-icon><Refresh /></el-icon>
                            </button>
                          </el-tooltip>
                          <el-tooltip content="从本集起续写" placement="top" :show-after="200">
                            <button
                              type="button"
                              class="ep-circle-act-btn"
                              :disabled="continuingEpisode"
                              @click.stop="onContinueFromEp(ep.episode_number)"
                            >
                              <el-icon><CaretRight /></el-icon>
                            </button>
                          </el-tooltip>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="filteredUnits.length === 0" class="ep-nav-empty">
                  未匹配到相关分集
                </div>
              </div>

              <!-- 底部操作按钮组 -->
              <div class="ep-nav-bottom-actions">
                <el-button
                  type="primary"
                  class="btn-batch-generate-range"
                  :loading="batchGenerating"
                  @click="onBatchGenerate(8, 17, 10)"
                >
                  ✨ 生成第 08-17 集 (10 集)
                </el-button>
                <el-button
                  size="default"
                  class="btn-batch-generate-next"
                  :loading="batchGenerating"
                  @click="onBatchGenerateNext3"
                >
                  ⏩ 生成下一批 (3 集)
                </el-button>
                <el-button
                  size="default"
                  class="btn-add-single-ep"
                  @click="openAddEpisodeDialog"
                >
                  <el-icon><Plus /></el-icon> 新增单集
                </el-button>
              </div>
            </aside>

            <!-- 2. 中部：AST 四分块剧本工作台 -->
            <main class="stage4-center-main-col" v-loading="loadingEpisodeDetail">
              <!-- 顶部集标题与元数据胶囊栏 -->
              <div class="center-top-header-card">
                <h2 class="current-ep-main-title">
                  第 {{ formatEpNum(currentEpisodeDetail.episode_num) }} 集：{{ currentEpisodeDetail.title }}
                </h2>
                <div class="center-meta-pills-row">
                  <span class="meta-pill-tag purple">
                    商业定位: {{ currentEpisodeDetail.commercial_tag }}
                  </span>
                  <span class="meta-pill-tag green">
                    质检 {{ currentEpisodeDetail.qa_score }} 放行
                  </span>
                  <span class="meta-pill-tag dark-gray">
                    🎬 场景 {{ currentEpisodeDetail.scenes }}
                  </span>
                  <span class="meta-pill-tag dark-gray">
                    👥 人物 {{ currentEpisodeDetail.characters }}
                  </span>
                  <span class="meta-pill-tag purple-light">
                    🔮 道具 {{ currentEpisodeDetail.props }}
                  </span>
                </div>
              </div>

              <!-- AST 四分块主体呈现容器 -->
              <div class="ast-blocks-display-container">
                <!-- 块 1 · 前3秒特写钩子 -->
                <div class="ast-card-block">
                  <div class="ast-block-header-label">
                    块 1 · 前3秒特写钩子
                  </div>
                  <div class="ast-block-body-shots">
                    <div
                      v-for="(shot, sIdx) in currentEpisodeDetail.ast_blocks?.block1?.shots"
                      :key="sIdx"
                      class="ast-shot-item-row"
                    >
                      <span class="shot-triangle">▲</span>
                      <strong class="shot-type-title">{{ shot.type }}:</strong>
                      <span class="shot-text-content" v-html="shot.text"></span>
                    </div>
                  </div>
                </div>

                <!-- 块 2 · 核心动作与场景 -->
                <div class="ast-card-block">
                  <div class="ast-block-header-label">
                    块 2 · 核心动作与场景
                  </div>
                  <div class="ast-block-body-shots">
                    <div
                      v-for="(shot, sIdx) in currentEpisodeDetail.ast_blocks?.block2?.shots"
                      :key="sIdx"
                      class="ast-shot-item-row"
                    >
                      <span class="shot-triangle">▲</span>
                      <strong class="shot-type-title">{{ shot.type }}:</strong>
                      <span class="shot-text-content" v-html="shot.text"></span>
                    </div>
                  </div>
                </div>

                <!-- 块 3 · 潜台词拉扯对白 -->
                <div class="ast-card-block with-patch-badge">
                  <div class="patch-badge-corner" v-if="currentEpisodeDetail.ast_blocks?.block3?.patched">
                    AI 已原位修补
                  </div>
                  <div class="ast-block-header-label">
                    块 3 · 潜台词拉扯对白
                  </div>
                  <div class="ast-dialogue-grid-box">
                    <div
                      v-for="(dia, dIdx) in currentEpisodeDetail.ast_blocks?.block3?.dialogues"
                      :key="dIdx"
                      class="dialogue-item-row"
                    >
                      <div class="dia-role-column">
                        <strong class="dia-role-text">{{ dia.role }}</strong>
                        <span class="dia-action-text">({{ dia.action }})</span>
                      </div>
                      <div class="dia-speech-column">
                        {{ dia.text }}
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 块 4 · 片尾定格与字幕悬念 -->
                <div class="ast-card-block with-patch-badge">
                  <div class="patch-badge-corner" v-if="currentEpisodeDetail.ast_blocks?.block4?.patched">
                    AI 已原位修补
                  </div>
                  <div class="ast-block-header-label">
                    块 4 · 片尾定格与字幕悬念
                  </div>
                  <div class="ast-block-body-shots">
                    <div
                      v-for="(shot, sIdx) in currentEpisodeDetail.ast_blocks?.block4?.shots"
                      :key="sIdx"
                      class="ast-shot-item-row"
                    >
                      <span class="shot-triangle">▲</span>
                      <strong
                        class="shot-type-title"
                        :class="{ 'amber-highlight': shot.type.includes('定格') }"
                      >
                        {{ shot.type }}:
                      </strong>
                      <span class="shot-text-content" v-html="shot.text"></span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 底部实时指标状态栏 -->
              <footer class="stage4-status-bottom-bar">
                <div class="status-metric-item">
                  <span class="metric-lbl">字数</span>
                  <strong class="metric-val">{{ currentEpisodeDetail.metrics?.word_count?.toLocaleString() || '1,286' }}</strong>
                </div>
                <div class="status-metric-item">
                  <span class="metric-lbl">Tokens</span>
                  <strong class="metric-val">{{ currentEpisodeDetail.metrics?.tokens?.toLocaleString() || '2,140' }}</strong>
                </div>
                <div class="status-metric-item">
                  <span class="metric-lbl">模型</span>
                  <strong class="metric-val">{{ currentEpisodeDetail.metrics?.model || 'Claude 3.5 Sonnet' }}</strong>
                </div>
                <div class="status-metric-item">
                  <span class="metric-lbl">耗时</span>
                  <strong class="metric-val">{{ currentEpisodeDetail.metrics?.duration_sec || '18.4' }}s</strong>
                </div>
                <div class="status-metric-item">
                  <span class="metric-lbl">自愈轮次</span>
                  <strong class="metric-val green-text">{{ currentEpisodeDetail.metrics?.auto_heal_round || '1 / 3' }}</strong>
                </div>
                <div class="status-metric-item">
                  <span class="metric-lbl">version_cursor</span>
                  <strong class="metric-val purple-text">{{ currentEpisodeDetail.metrics?.version_cursor || '#47' }}</strong>
                </div>
                <div class="status-metric-item sse-item">
                  <span class="sse-pulse-circle"></span>
                  <span class="sse-label">SSE 已连接</span>
                </div>
              </footer>
            </main>

            <!-- 3. 右侧：质检与连续性侧边栏 -->
            <aside class="stage4-quality-sidebar-col">
              <div class="qa-side-top-header">
                <span class="qa-side-title">质检与连续性</span>
                <span class="qa-realtime-pill">实时</span>
              </div>

              <div class="qa-side-scrollable-content">
                <!-- 综合得分卡片 -->
                <div class="qa-score-main-card">
                  <div class="qa-score-big-number">{{ currentEpisodeDetail.qa_score || 92 }}</div>
                  <div class="qa-score-desc-title">五阶闭环质检综合得分</div>
                  <div class="qa-score-pass-badge">✓ 放行 (≥85)</div>

                  <!-- SVG 五维雷达图 -->
                  <div class="qa-radar-svg-wrapper">
                    <svg viewBox="0 0 240 200" class="radar-svg">
                      <!-- 蛛网背景多边形 -->
                      <polygon points="120,25 200,80 170,165 70,165 40,80" fill="none" stroke="currentColor" stroke-opacity="0.12" stroke-width="1" />
                      <polygon points="120,50 170,88 150,140 90,140 70,88" fill="none" stroke="currentColor" stroke-opacity="0.08" stroke-width="1" />
                      <polygon points="120,75 145,95 135,120 105,120 95,95" fill="none" stroke="currentColor" stroke-opacity="0.06" stroke-width="1" />
                      <!-- 中心向外轴线 -->
                      <line x1="120" y1="100" x2="120" y2="25" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                      <line x1="120" y1="100" x2="200" y2="80" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                      <line x1="120" y1="100" x2="170" y2="165" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                      <line x1="120" y1="100" x2="70" y2="165" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                      <line x1="120" y1="100" x2="40" y2="80" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />

                      <!-- 评分覆盖区域 (紫色半透明多边形) -->
                      <polygon
                        points="120,28 192,82 165,158 75,155 46,84"
                        fill="rgba(139, 92, 246, 0.25)"
                        stroke="#8b5cf6"
                        stroke-width="2"
                        stroke-linejoin="round"
                      />
                      <!-- 数据顶点圆点 -->
                      <circle cx="120" cy="28" r="3" fill="#8b5cf6" />
                      <circle cx="192" cy="82" r="3" fill="#8b5cf6" />
                      <circle cx="165" cy="158" r="3" fill="#8b5cf6" />
                      <circle cx="75" cy="155" r="3" fill="#8b5cf6" />
                      <circle cx="46" cy="84" r="3" fill="#8b5cf6" />
                    </svg>

                    <!-- 五维指标数值标签栏 -->
                    <div class="radar-metrics-labels-grid">
                      <div class="radar-lbl top">结构 <span class="val green">24/25</span></div>
                      <div class="radar-lbl right-top">人物 <span class="val green">19/20</span></div>
                      <div class="radar-lbl right-bottom">视听 <span class="val green">18/20</span></div>
                      <div class="radar-lbl left-bottom">语言 <span class="val orange">14/15</span></div>
                      <div class="radar-lbl left-top">连续性 <span class="val green">17/20</span></div>
                    </div>
                  </div>
                </div>

                <!-- 缺陷定位与局部修补 -->
                <div class="qa-section-card">
                  <div class="qa-card-header-title">
                    <span class="icon">✏</span> 缺陷定位与局部修补
                  </div>
                  <div class="qa-patches-list">
                    <div
                      v-for="patch in currentEpisodeDetail.qa_patches"
                      :key="patch.id"
                      class="qa-patch-item-box"
                      :class="patch.type"
                    >
                      <div class="patch-box-top">
                        <span class="patch-tag-pill" :class="patch.type">{{ patch.tag }}</span>
                        <strong class="patch-box-title">{{ patch.title }}</strong>
                      </div>
                      <div class="patch-box-desc">{{ patch.desc }}</div>
                    </div>
                  </div>
                </div>

                <!-- 角色实时信息差矩阵 -->
                <div class="qa-section-card">
                  <div class="qa-card-header-title">
                    <span class="icon">👁</span> 角色实时信息差矩阵
                  </div>
                  <div class="qa-info-gaps-list">
                    <div
                      v-for="gap in currentEpisodeDetail.character_info_gaps"
                      :key="gap.name"
                      class="info-gap-item-box"
                    >
                      <div class="gap-char-header">👤 {{ gap.name }}</div>
                      <div class="gap-row">
                        <span class="gap-badge-label known">知晓</span>
                        <span class="gap-text-detail">{{ gap.known }}</span>
                      </div>
                      <div class="gap-row">
                        <span class="gap-badge-label unknown">未知</span>
                        <span class="gap-text-detail">{{ gap.unknown }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </aside>
          </div>
        </div>

        <!-- 阶段 5：复盘定稿与全剧归宿校验 (高保真全屏看板 + 底部固定核心操作交互栏) -->
        <div v-show="activeTab === 'stage5_finalize'" class="stage-content-view stage5-full-view" v-loading="loadingFinalizeAudit">
          <!-- 1. 顶部标题与全剧汇总卡片 -->
          <div class="stage5-header-title-bar">
            <h1 class="stage-main-title">5. 阶段复盘与全剧归宿校验</h1>
          </div>

          <div class="stage5-top-summary-card">
            <div class="top-sum-left">
              <div class="sum-title-row">
                <h2 class="sum-drama-name">{{ finalizeAuditData.drama_title || drama?.title || '头七夜的第七封信' }}</h2>
                <span class="sum-tag-pill purple">{{ finalizeAuditData.commercial_tag || '都市悬疑 · 亲情复仇' }}</span>
                <span
                  class="sum-tag-pill status"
                  :class="finalizeAuditData.lock_status === 1 ? 'locked' : 'pending'"
                >
                  {{ finalizeAuditData.lock_status === 1 ? '已定稿锁定' : '待定稿' }}
                </span>
              </div>
              <div class="sum-desc-text">
                共 {{ finalizeAuditData.total_episodes || totalCount || 80 }} 集 · 单集 90 秒 · 全剧已生成 {{ finalizeAuditData.generated_episodes || totalCount || 80 }}/{{ finalizeAuditData.total_episodes || totalCount || 80 }} 集 (100%)
              </div>
            </div>

            <div class="top-sum-metrics-grid">
              <div class="sum-metric-box">
                <span class="m-lbl">完成进度</span>
                <strong class="m-val green">{{ finalizeAuditData.completion_percent || '100%' }}</strong>
              </div>
              <div class="sum-metric-box">
                <span class="m-lbl">总字数</span>
                <strong class="m-val">{{ finalizeAuditData.word_count_wan || '18.6 万' }}</strong>
              </div>
              <div class="sum-metric-box">
                <span class="m-lbl">预计时长</span>
                <strong class="m-val">{{ finalizeAuditData.duration_minutes || '120 分钟' }}</strong>
              </div>
              <div class="sum-metric-box">
                <span class="m-lbl">合格集数</span>
                <strong class="m-val">{{ finalizeAuditData.qualified_episodes || '77/80' }}</strong>
              </div>
              <div class="sum-metric-box">
                <span class="m-lbl">版本游标</span>
                <strong class="m-val purple">{{ finalizeAuditData.version_tag || 'v7.2-final' }}</strong>
              </div>
              <div class="sum-metric-box lock-box">
                <span class="lock-status-tag" :class="finalizeAuditData.lock_status === 1 ? 'is-locked' : 'is-unlocked'">
                  🔒 lock_status = {{ finalizeAuditData.lock_status || 0 }} ({{ finalizeAuditData.lock_status === 1 ? '已冻结' : '可编辑' }})
                </span>
              </div>
            </div>
          </div>

          <!-- 2. 全剧五阶质检雷达大屏 (Global Five-Stage QA & Radar Analytics) -->
          <section class="stage5-section-card">
            <div class="section-badge-header">
              <span class="badge-number">2</span>
              <span class="badge-title">全剧五阶质检雷达大屏</span>
              <span class="badge-subtitle">Global Five-Stage QA & Radar Analytics</span>
            </div>

            <div class="radar-analytics-two-col">
              <!-- 左列：大总分 + 满分权重 + 警示 + SVG 五维雷达图 -->
              <div class="radar-left-panel">
                <div class="overall-health-score-num">
                  {{ finalizeAuditData.radar_analytics?.overall_health_score || '92.8' }}
                </div>
                <div class="overall-score-lbl">全剧综合健康总分 (加权)</div>
                <div class="overall-weights-desc">
                  {{ finalizeAuditData.radar_analytics?.weights_desc || '五阶满分 100: 结构 25 / 人物 20 / 场景 20 / 台词 20 / 卡点 15' }}
                </div>
                <div class="low-score-warn-badge">
                  低于 85 分的集数 <strong class="warn-count">{{ finalizeAuditData.radar_analytics?.low_score_count || 3 }} 集</strong>
                  ({{ finalizeAuditData.radar_analytics?.low_score_episodes?.join('、') || 'E11、E19、E64' }})
                </div>

                <!-- SVG 五维雷达图 -->
                <div class="global-radar-svg-box">
                  <svg viewBox="0 0 280 240" class="global-radar-svg">
                    <!-- 背景多边形蛛网 -->
                    <polygon points="140,25 240,88 205,195 75,195 40,88" fill="none" stroke="currentColor" stroke-opacity="0.12" stroke-width="1" />
                    <polygon points="140,55 210,98 185,170 95,170 70,98" fill="none" stroke="currentColor" stroke-opacity="0.08" stroke-width="1" />
                    <polygon points="140,85 180,110 165,150 115,150 100,110" fill="none" stroke="currentColor" stroke-opacity="0.06" stroke-width="1" />
                    <!-- 轴线 -->
                    <line x1="140" y1="125" x2="140" y2="25" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                    <line x1="140" y1="125" x2="240" y2="88" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                    <line x1="140" y1="125" x2="205" y2="195" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                    <line x1="140" y1="125" x2="75" y2="195" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />
                    <line x1="140" y1="125" x2="40" y2="88" stroke="currentColor" stroke-opacity="0.1" stroke-width="1" />

                    <!-- 数据覆盖区域 (紫色多边形) -->
                    <polygon
                      points="140,32 232,92 198,188 82,185 48,92"
                      fill="rgba(139, 92, 246, 0.28)"
                      stroke="#8b5cf6"
                      stroke-width="2.5"
                      stroke-linejoin="round"
                    />
                    <circle cx="140" cy="32" r="3.5" fill="#8b5cf6" />
                    <circle cx="232" cy="92" r="3.5" fill="#8b5cf6" />
                    <circle cx="198" cy="188" r="3.5" fill="#8b5cf6" />
                    <circle cx="82" cy="185" r="3.5" fill="#8b5cf6" />
                    <circle cx="48" cy="92" r="3.5" fill="#8b5cf6" />
                  </svg>

                  <!-- 雷达图周围标签 -->
                  <div class="radar-node-label top">结构节奏 <span class="val">23.4/25</span></div>
                  <div class="radar-node-label right-top">人物塑造 <span class="val">18.6/20</span></div>
                  <div class="radar-node-label right-bottom">场景视听 <span class="val">18.2/20</span></div>
                  <div class="radar-node-label left-bottom">台词对白 <span class="val">17.9/20</span></div>
                  <div class="radar-node-label left-top">商业卡点 <span class="val">14.7/15</span></div>
                </div>
              </div>

              <!-- 右列：五项质检进度条 + AST 局部修补自愈统计 -->
              <div class="radar-right-panel">
                <div class="qa-dim-bars-list">
                  <div
                    v-for="dim in finalizeAuditData.radar_analytics?.dimensions || []"
                    :key="dim.name"
                    class="qa-dim-bar-item"
                  >
                    <div class="dim-bar-lbl">{{ dim.name }}</div>
                    <div class="dim-bar-track">
                      <div
                        class="dim-bar-fill"
                        :style="{ width: dim.percent + '%', backgroundColor: dim.color || '#10b981' }"
                      />
                    </div>
                    <div class="dim-bar-score">
                      <strong class="sc-curr">{{ dim.score }}</strong>
                      <span class="sc-max">/{{ dim.max }}</span>
                    </div>
                  </div>
                </div>

                <!-- AST 手术式局部修补自愈统计 -->
                <div class="ast-heal-analytics-box">
                  <div class="heal-box-head">
                    <div class="heal-head-title">
                      <span class="icon">✏</span> AST 手术式局部修补自愈统计
                    </div>
                    <div class="heal-head-sub">不重写全篇，仅原位替换缺陷分块</div>
                  </div>

                  <div class="heal-stats-cards-grid">
                    <div class="heal-stat-card">
                      <span class="st-lbl">自愈轮次</span>
                      <strong class="st-val purple">{{ finalizeAuditData.radar_analytics?.ast_heal_stats?.heal_rounds || 186 }}</strong>
                    </div>
                    <div class="heal-stat-card">
                      <span class="st-lbl">修补分块</span>
                      <strong class="st-val">{{ finalizeAuditData.radar_analytics?.ast_heal_stats?.patched_blocks || 412 }}</strong>
                    </div>
                    <div class="heal-stat-card">
                      <span class="st-lbl">一次通过</span>
                      <strong class="st-val green">{{ finalizeAuditData.radar_analytics?.ast_heal_stats?.first_pass_count || 397 }}</strong>
                    </div>
                    <div class="heal-stat-card">
                      <span class="st-lbl">自愈成功率</span>
                      <strong class="st-val green">{{ finalizeAuditData.radar_analytics?.ast_heal_stats?.heal_success_rate || '96.4%' }}</strong>
                    </div>
                  </div>

                  <div class="heal-bottom-desc">
                    平均每集触发 2.3 轮自愈，单次修补约 1840 Tokens；相比整篇重写节省约 <strong>94%</strong> 的 Token 消耗。
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 3. 全剧全集交付矩阵与导出中心 (Episode Delivery Matrix & Export Center) -->
          <section class="stage5-section-card">
            <div class="section-badge-header between">
              <div class="header-left-part">
                <span class="badge-number">3</span>
                <span class="badge-title">全剧全集交付矩阵与导出中心</span>
                <span class="badge-subtitle">Episode Delivery Matrix & Export Center</span>
              </div>
            </div>

            <!-- 统计标签与筛选 Tabs -->
            <div class="delivery-matrix-filter-bar">
              <div class="matrix-stats-pills">
                <span class="matrix-pill purple">{{ totalCount || 80 }} 集 × 4 镜头 = {{ (totalCount || 80) * 4 }} 镜头</span>
                <span class="matrix-pill green">合格 {{ finalizeAuditData.delivery_matrix?.qualified_count || 77 }}</span>
                <span class="matrix-pill orange">待修补 {{ finalizeAuditData.delivery_matrix?.need_patch_count || 3 }}</span>
              </div>

              <div class="matrix-filter-tabs">
                <button
                  type="button"
                  class="matrix-tab-btn"
                  :class="{ active: matrixFilterType === 'all' }"
                  @click="matrixFilterType = 'all'"
                >
                  全部 {{ totalCount || 80 }} 集
                </button>
                <button
                  type="button"
                  class="matrix-tab-btn"
                  :class="{ active: matrixFilterType === 'paywall' }"
                  @click="matrixFilterType = 'paywall'"
                >
                  付费卡点
                </button>
                <button
                  type="button"
                  class="matrix-tab-btn"
                  :class="{ active: matrixFilterType === 'reversal' }"
                  @click="matrixFilterType = 'reversal'"
                >
                  反转集
                </button>
                <button
                  type="button"
                  class="matrix-tab-btn"
                  :class="{ active: matrixFilterType === 'low_score' }"
                  @click="matrixFilterType = 'low_score'"
                >
                  低分待修补
                </button>
              </div>
            </div>

            <!-- 全集网格矩阵 (80 集 Grid) -->
            <div class="episodes-delivery-grid">
              <div
                v-for="ep in filteredMatrixEpisodes"
                :key="ep.episode_number"
                class="matrix-ep-card"
                :class="{
                  'is-active': selectedMatrixEp?.episode_number === ep.episode_number,
                  'is-low-score': ep.need_patch || (ep.score && ep.score < 85),
                  'has-paywall': ep.is_paywall
                }"
                @click="onSelectMatrixEpisode(ep)"
              >
                <!-- 卡点标记小圆点 -->
                <span v-if="ep.is_paywall" class="ep-paywall-dot" title="核心付费卡点" />

                <div class="ep-card-top-num">E{{ formatEpNum(ep.episode_number) }}</div>
                <div class="ep-card-score" :class="ep.score < 85 ? 'red' : (ep.score >= 90 ? 'green' : 'orange')">
                  {{ ep.score }}
                </div>
                <div class="ep-card-title-text" :title="ep.title">{{ ep.title }}</div>
              </div>
            </div>

            <!-- 导出中心快捷卡片行 -->
            <div class="export-center-action-grid">
              <div class="export-act-card" @click="openExportDialog('all')">
                <div class="export-card-icon">📦</div>
                <div class="export-card-content">
                  <div class="export-card-title">全剧打包导出</div>
                  <div class="export-card-sub">PDF + Word + CSV + JSON 一次导出</div>
                </div>
              </div>

              <div class="export-act-card" @click="openExportDialog('audit_report')">
                <div class="export-card-icon">📊</div>
                <div class="export-card-content">
                  <div class="export-card-title">生成复盘报告</div>
                  <div class="export-card-sub">质检 / 伏笔 / 卡点 / 成本四维汇总</div>
                </div>
              </div>
            </div>
          </section>

          <!-- 4. 角色弧光与伏笔回收复盘看板 (Character Arc & Clue Closure Audit) -->
          <section class="stage5-section-card">
            <div class="section-badge-header">
              <span class="badge-number">4</span>
              <span class="badge-title">角色弧光与伏笔回收复盘看板</span>
              <span class="badge-subtitle">Character Arc & Clue Closure Audit</span>
            </div>

            <!-- 角色弧光 2 列网格 -->
            <div class="char-arc-cards-grid">
              <div
                v-for="char in finalizeAuditData.character_arcs || []"
                :key="char.id"
                class="char-arc-audit-card"
              >
                <div class="char-arc-head-row">
                  <div class="char-avatar-mini-box">👤</div>
                  <div class="char-name-col">
                    <strong class="c-name">{{ char.name }}</strong>
                    <span class="c-status">current_status = {{ char.current_status }}</span>
                  </div>
                </div>

                <div class="char-arc-state-shift-box">
                  <div class="state-pill init">{{ char.initial_state }}</div>
                  <span class="state-arrow">→</span>
                  <div class="state-pill end">{{ char.end_state }}</div>
                </div>

                <div class="char-arc-timeline-list">
                  <div
                    v-for="(node, nIdx) in char.timeline"
                    :key="nIdx"
                    class="arc-timeline-item"
                  >
                    <span class="arc-ep-tag">{{ node.ep }}</span>
                    <span class="arc-text">{{ node.text }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 全剧伏笔回收率看板 -->
            <div class="clue-closure-audit-block">
              <div class="clue-audit-top-bar">
                <div class="clue-title-part">
                  <span class="icon">⏳</span> 全剧伏笔回收率
                </div>
                <div class="clue-count-part">
                  {{ finalizeAuditData.clue_closures?.total_clues || 12 }} 条伏笔 · 已回收 {{ finalizeAuditData.clue_closures?.recovered_count || 9 }} 条
                </div>
              </div>

              <!-- 4 个统计指标块 -->
              <div class="clue-stats-quad-grid">
                <div class="clue-stat-card">
                  <span class="c-lbl">已回收</span>
                  <strong class="c-val green">{{ finalizeAuditData.clue_closures?.recovered_count || 9 }}</strong>
                </div>
                <div class="clue-stat-card">
                  <span class="c-lbl">待补全</span>
                  <strong class="c-val orange">{{ finalizeAuditData.clue_closures?.pending_count || 1 }}</strong>
                </div>
                <div class="clue-stat-card">
                  <span class="c-lbl">未回收</span>
                  <strong class="c-val red">{{ finalizeAuditData.clue_closures?.unrecovered_count || 2 }}</strong>
                </div>
                <div class="clue-stat-card">
                  <span class="c-lbl">回收率</span>
                  <strong class="c-val">{{ finalizeAuditData.clue_closures?.recovery_rate || '75.0%' }}</strong>
                </div>
              </div>

              <!-- 伏笔条目列表 -->
              <div class="clue-items-list-container">
                <div
                  v-for="clue in finalizeAuditData.clue_closures?.items || []"
                  :key="clue.id"
                  class="clue-item-row-card"
                  :class="clue.status_type"
                >
                  <div class="clue-id-badge">{{ clue.id }}</div>
                  <div class="clue-name-and-path">
                    <div class="c-main-name">{{ clue.name }}</div>
                    <div class="c-path-text">{{ clue.path_desc }}</div>
                  </div>
                  <div class="clue-status-end-box">
                    <span class="clue-ep-range">{{ clue.buried_ep }} → {{ clue.resolved_ep }}</span>
                    <span
                      class="clue-status-pill"
                      :class="clue.status_type"
                      @click="onClickClueStatus(clue)"
                    >
                      {{ clue.status }}
                      <span v-if="clue.status_type !== 'recovered'" class="clue-heal-hint">⚡一键补全</span>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 5. Script-to-Visual Bridge · 视听镜头资产就绪看板 (Storyboard & Visual Pipeline Readiness) -->
          <section class="stage5-section-card">
            <div class="section-badge-header">
              <span class="badge-number">5</span>
              <span class="badge-title">Script-to-Visual Bridge · 视听镜头资产就绪看板</span>
              <span class="badge-subtitle">Storyboard & Visual Pipeline Readiness</span>
            </div>

            <div class="visual-bridge-two-col">
              <!-- 左侧：分镜镜头生成概况 + 景别分布 -->
              <div class="bridge-left-col">
                <div class="sub-block-header-row">
                  <span class="sub-blk-title">🎬 分镜镜头生成概况</span>
                  <span class="sub-blk-tag">全剧 {{ (totalCount || 80) * 4 }} 镜头 · 每集 4 镜头</span>
                </div>

                <div class="pipeline-progress-bars-list">
                  <div class="pipe-bar-item">
                    <span class="pipe-lbl">🖼️ 文生图</span>
                    <div class="pipe-track">
                      <div class="pipe-fill" style="width: 0%;" />
                    </div>
                    <span class="pipe-count">0/{{ (totalCount || 80) * 4 }}</span>
                  </div>
                  <div class="pipe-bar-item">
                    <span class="pipe-lbl">🎥 图生视频</span>
                    <div class="pipe-track">
                      <div class="pipe-fill" style="width: 0%;" />
                    </div>
                    <span class="pipe-count">0/{{ (totalCount || 80) * 4 }}</span>
                  </div>
                  <div class="pipe-bar-item">
                    <span class="pipe-lbl">🔊 TTS 配音</span>
                    <div class="pipe-track">
                      <div class="pipe-fill" style="width: 0%;" />
                    </div>
                    <span class="pipe-count">0/{{ (totalCount || 80) * 4 }}</span>
                  </div>
                  <div class="pipe-bar-item">
                    <span class="pipe-lbl">🎲 Seed 锚点</span>
                    <div class="pipe-track">
                      <div class="pipe-fill green-full" style="width: 100%;" />
                    </div>
                    <span class="pipe-count green">{{ (totalCount || 80) * 4 }}/{{ (totalCount || 80) * 4 }}</span>
                  </div>
                </div>

                <div class="pipe-desc-note">
                  Seed 锚点已随 Bridge 契约预置 ({{ (totalCount || 80) * 4 }} 个)，保证角色一致性；文生图 / 图生视频 / 配音将在转入画布后按需生成。
                </div>

                <!-- 预置分镜景别分布 -->
                <div class="shot-dist-header-row">
                  <span class="shot-dist-title">📐 预置分镜景别分布</span>
                  <span class="shot-dist-tag">5 类景别</span>
                </div>
                <div class="shot-dist-bars-list">
                  <div
                    v-for="st in finalizeAuditData.visual_bridge_readiness?.shot_distributions || []"
                    :key="st.type"
                    class="shot-dist-bar-item"
                  >
                    <span class="s-type-lbl">{{ st.type }}</span>
                    <div class="s-track">
                      <div class="s-fill" :style="{ width: st.weight + '%', backgroundColor: st.color }" />
                    </div>
                    <span class="s-pct-val">{{ st.percent }}</span>
                  </div>
                </div>
                <div class="shot-dist-note">
                  特写 + 近景占比 <strong>65%</strong>，符合竖屏短剧的观看距离与情绪传达需求。
                </div>
              </div>

              <!-- 右侧：关键反转节点配乐音效库 -->
              <div class="bridge-right-col">
                <div class="sub-block-header-row">
                  <span class="sub-blk-title">🎵 关键反转节点配乐音效库</span>
                  <span class="sub-blk-tag">music_cues · 6 个关键节点</span>
                </div>

                <div class="music-cues-cards-list">
                  <div
                    v-for="mc in finalizeAuditData.visual_bridge_readiness?.music_cues || []"
                    :key="mc.id"
                    class="music-cue-item-card"
                  >
                    <div class="mc-icon">🎻</div>
                    <div class="mc-ep-tag">{{ mc.ep }}</div>
                    <div class="mc-action-title">{{ mc.action }}</div>
                    <div class="mc-motif-desc">{{ mc.motif }}</div>
                    <div class="mc-bpm-tag">{{ mc.bpm }}</div>
                    <div class="mc-duration-tag">{{ mc.duration }}</div>
                  </div>
                </div>

                <div class="music-cues-note">
                  全部动机已在阶段 2 故事圣经中定义，此处仅绑定反转节点位置与时长。
                </div>
              </div>
            </div>
          </section>

          <!-- 底部常驻核心操作交互栏 (Sticky Bottom) -->
          <footer class="stage5-sticky-bottom-bar">
            <div class="bottom-interact-content">
              <div class="bottom-warning-row">
                <div class="warn-icon-box">
                  <span v-if="!finalizeAuditData.checklist?.qa_passed || !finalizeAuditData.checklist?.clues_passed">⚠️</span>
                  <span v-else>✅</span>
                </div>
                <div class="warn-text-col">
                  <strong class="warn-main-title">核心操作交互栏</strong>
                  <span class="warn-sub-msg">{{ finalizeAuditData.checklist?.warning_text || '仍有 2 条伏笔未回收、3 集低于 85 分，建议先处理再定稿' }}</span>
                </div>
                <div class="bottom-action-buttons-group">
                  <el-button class="btn-report" @click="openExportDialog('audit_report')">
                    📊 复盘报告
                  </el-button>
                  <el-button
                    v-if="finalizeAuditData.lock_status !== 1"
                    type="primary"
                    class="btn-lock-freeze"
                    :loading="locking"
                    @click="onLockAndFreeze"
                  >
                    🔒 确定定稿并冻结版本
                  </el-button>
                  <el-button
                    v-else
                    type="warning"
                    class="btn-unlock"
                    :loading="locking"
                    @click="onUnlockScript"
                  >
                    🔓 解除定稿锁定
                  </el-button>
                  <el-button
                    type="primary"
                    class="btn-goto-canvas"
                    :loading="locking"
                    @click="onFinalizeAndBridge"
                  >
                    🎬 一键转入视听制作画布
                  </el-button>
                </div>
              </div>

              <!-- 底部状态检验胶囊条 -->
              <div class="bottom-checklist-pills-row">
                <div class="check-pill green">
                  <span class="chk-mark">✓</span> 上游四阶段已通过
                </div>
                <div class="check-pill" :class="finalizeAuditData.delivery_matrix?.need_patch_count > 0 ? 'orange' : 'green'">
                  <span class="chk-mark">{{ finalizeAuditData.delivery_matrix?.need_patch_count > 0 ? '!' : '✓' }}</span>
                  分集质检 ≥ 85 ({{ finalizeAuditData.delivery_matrix?.need_patch_count || 0 }} 集待修补)
                </div>
                <div class="check-pill" :class="finalizeAuditData.clue_closures?.unrecovered_count > 0 ? 'red' : 'green'">
                  <span class="chk-mark">{{ finalizeAuditData.clue_closures?.unrecovered_count > 0 ? '✕' : '✓' }}</span>
                  伏笔回收 ({{ finalizeAuditData.clue_closures?.unrecovered_count || 0 }} 未回收)
                </div>
                <div class="check-pill green">
                  <span class="chk-mark">✓</span> 全剧健康分 {{ finalizeAuditData.radar_analytics?.overall_health_score || '92.8' }}
                </div>
                <div class="check-pill" :class="finalizeAuditData.lock_status === 1 ? 'green' : 'gray'">
                  <span class="chk-mark">{{ finalizeAuditData.lock_status === 1 ? '✓' : '○' }}</span>
                  {{ finalizeAuditData.lock_status === 1 ? '已定稿冻结' : '待冻结' }}
                </div>
              </div>
            </div>
          </footer>
        </div>
      </main>
    </div>

    <!-- 阶段 5 导出中心与复盘报告弹窗 -->
    <el-dialog
      v-model="exportDialogVisible"
      title="全剧工业化交付中心与复盘报告导出"
      width="640px"
      destroy-on-close
      class="export-dialog-box"
    >
      <div class="export-dialog-body" v-loading="exporting">
        <div class="export-summary-box">
          <div class="ex-name">📦 {{ finalizeAuditData.drama_title || '头七夜的第七封信' }}_全剧交付资产包</div>
          <div class="ex-meta">包含标准工业化台本、五阶质检报告、AST结构元数据及分镜资产表</div>
        </div>

        <div class="export-files-list">
          <div
            v-for="file in exportFileList"
            :key="file.name"
            class="export-file-item"
          >
            <div class="f-icon">📄</div>
            <div class="f-info">
              <strong class="f-title">{{ file.name }}</strong>
              <span class="f-size">{{ file.size }} · {{ file.format }}</span>
            </div>
            <el-button size="small" type="primary" link @click="downloadMockFile(file)">
              下载
            </el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="exportDialogVisible = false">关闭</el-button>
          <el-button type="primary" :loading="exporting" @click="handleBatchDownloadAll">
            一键打包下载全部交付物 (.zip)
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 阶段 5 单集自愈/详情弹窗 -->
    <el-dialog
      v-model="healDialogVisible"
      :title="selectedMatrixEp ? `第 ${formatEpNum(selectedMatrixEp.episode_number)} 集 · ${selectedMatrixEp.title}` : '单集质检与自愈'"
      width="520px"
      destroy-on-close
    >
      <div v-if="selectedMatrixEp" class="heal-dialog-body">
        <div class="ep-heal-score-row">
          <span>当前质检分: <strong :class="selectedMatrixEp.score < 85 ? 'red' : 'green'">{{ selectedMatrixEp.score }} 分</strong></span>
          <span>商业标签: <strong>{{ selectedMatrixEp.commercial_tag }}</strong></span>
        </div>
        <p class="ep-heal-tip" v-if="selectedMatrixEp.score < 85">
          ⚠️ 本集质检得分低于 85 分放行阈值，存在对白潜台词偏弱或片尾卡点断章不充分问题。点击下方按钮可触发 AST 手术式原位替换自愈。
        </p>
        <p class="ep-heal-tip green-tip" v-else>
          ✓ 本集已通过五阶质检，符合工业化剧本交付标准。
        </p>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="healDialogVisible = false">关闭</el-button>
          <el-button
            type="warning"
            :loading="healingEp"
            v-if="selectedMatrixEp?.score < 85"
            @click="confirmHealEpisode(selectedMatrixEp.episode_number)"
          >
            ⚡ 执行 AST 局部自愈提分
          </el-button>
          <el-button type="primary" @click="viewEpisodeInStage4(selectedMatrixEp.episode_number)">
            进入阶段 4 查看 AST 剧本
          </el-button>
        </div>
      </template>
    </el-dialog>
      </main>
    </div>

    <!-- 新增单集弹窗组件 -->
    <el-dialog
      v-model="addEpisodeDialogVisible"
      title="新增分集"
      width="520px"
      destroy-on-close
      class="add-ep-dialog"
    >
      <el-form :model="addEpisodeForm" label-width="90px" label-position="left">
        <el-form-item label="集数序号">
          <el-input-number v-model="addEpisodeForm.episode_number" :min="1" :max="200" style="width: 100%" />
        </el-form-item>
        <el-form-item label="分集标题" required>
          <el-input v-model="addEpisodeForm.title" placeholder="如：第 08 集 · 隐秘暗格" />
        </el-form-item>
        <el-form-item label="商业定位">
          <el-select v-model="addEpisodeForm.commercial_tag" style="width: 100%">
            <el-option label="常规剧情集" value="常规剧情集" />
            <el-option label="核心情绪爆点" value="核心情绪爆点" />
            <el-option label="付费卡点前哨" value="付费卡点前哨" />
            <el-option label="核心付费卡点" value="核心付费卡点" />
            <el-option label="大结局清算" value="大结局清算" />
          </el-select>
        </el-form-item>
        <el-form-item label="剧情大纲">
          <el-input
            v-model="addEpisodeForm.description"
            type="textarea"
            :rows="3"
            placeholder="简要填写本集主要动作、反转与片尾悬念"
          />
        </el-form-item>
        <el-form-item label="期望时长">
          <el-input-number v-model="addEpisodeForm.duration" :min="30" :max="300" :step="10" /> 秒
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="addEpisodeDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="addingSingleEpisode" @click="confirmAddSingleEpisode">
            确认新增
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- AI 配置弹窗组件 -->
    <el-dialog v-model="showAiConfigDialog" title="AI 配置" width="90%" destroy-on-close>
      <AIConfigContent v-if="showAiConfigDialog" />
    </el-dialog>

    <!-- 工作流运行抽屉组件 -->
    <WorkflowRunDrawer
      v-model:visible="showWorkflowDrawer"
      :drama-id="dramaId"
      :episode-id="currentEpisodeId"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  FolderOpened, ArrowDown, Grid, Operation, Sunny, Moon, Setting, Lock, Check, Plus, DocumentAdd, Close, Refresh, CaretRight, Search
} from '@element-plus/icons-vue'
import { useTheme } from '@/composables/useTheme'
import { dramaAPI } from '@/api/drama'
import { scriptStudioAPI } from '@/api/scriptStudio'
import AIConfigContent from '@/components/AIConfigContent.vue'
import WorkflowRunDrawer from '@/components/WorkflowRunDrawer.vue'

const route = useRoute()
const router = useRouter()
const { isDark, toggle: toggleTheme } = useTheme()

const dramaId = computed(() => Number(route.params.id) || 0)
const drama = ref(null)
const allDramas = ref([])

// 界面状态
const activeTab = ref('story_input') // story_input, stage1_concept, stage2_bible, stage3_outline, stage4_script, stage5_finalize
const workbenchMode = ref('create')
const showAiConfigDialog = ref(false)
const showWorkflowDrawer = ref(false)
const showNovelImportDialog = ref(false)

// 表单输入与配置
const storyPrompt = ref('记者林晚在母亲苏秀兰头七当晚，收到一封母亲生前寄给自己的信——七封信的最后一封，写着「囡囡，别查周家」。她顺着信里的线索回到老宅，却发现母亲的死，和二十年前周氏工厂那场被定为意外的火灾，牵着同一根线。刑警周行找上门来，他说他母亲也死在那场火里。')
const genreOptions = ['现代', '古装', '都市', '年代', '玄幻']
const selectedGenre = ref('现代')

const typeOptions = ['剧情', '悬疑', '复仇', '甜宠', '逆袭', '家庭']
const selectedType = ref('剧情')

const episodeCount = ref(80)
const episodeDuration = ref('90s')
const paywallEpisodes = ref('10,15,20')

const concurrencyOptions = [
  { label: '1 集串行', val: '1' },
  { label: '2~3 集/批', val: '2-3' },
  { label: '4~5 集/批', val: '4-5' }
]
const selectedConcurrency = ref('2-3')

// HITL 人工审核
const isHitlEnabled = ref(true)
const hitlStrategy = ref('strict') // strict, key_nodes, auto
const isPipelinePaused = ref(false)
const pausedNode = ref('')

// 状态机执行与轮询
const pipelineRunning = ref(false)
const resuming = ref(false)
const locking = ref(false)
let eventSource = null

// 统计数据
const generatedCount = ref(7)
const totalCount = ref(80)
const avgScore = ref(92)
const characterCount = ref(3)
const propCount = ref(2)
const sceneCount = ref(5)
const storyboardCount = ref(6)

// 阶段 1：创意立项与高概念完整数据模型
const isEditingConcept = ref(false)
const savingConcept = ref(false)
const regeneratingConcept = ref(false)

const conceptData = ref({
  hitl_passed: true,
  one_sentence_hook: '母亲头七当晚，她收到母亲生前寄给自己的第七封信——而落款日期，是她死后的第三天。',
  hook_analysis: {
    text: '悬念前置 + 超自然反常（死后寄信），3 秒内同时给出「丧母之痛」与「逻辑悖论」双重刺激，是竖屏短剧前 3 秒完播率最高的钩子结构。',
    play_rate_3s: '78%',
    suspense_score: '9.1',
    emotion_score: '8.4',
    info_entropy: '中'
  },
  four_acts: {
    cause: {
      ep_range: 'E01-E10',
      title: '起因',
      content: '记者林晚接到母亲苏秀兰"自杀"的噩耗，回老宅奔丧。头七夜，她在供桌下发现七封母亲亲笔信，前六封写给外人，唯独第七封写着"囡囡，别查周家"。她认定母亲的死另有隐情。'
    },
    development: {
      ep_range: 'E11-E30',
      title: '发展',
      content: '林晚以记者身份切入二十年前周氏工厂那场"意外"火灾，层层剥开：当年死亡的七名女工、被压下的质检报告、以及母亲作为会计留下的账本。刑警周行主动接近她——她不知道，周行的母亲也死在那场火里。'
    },
    climax: {
      ep_range: 'E31-E60',
      title: '高潮',
      content: '第七封信末尾的隐形字浮出："手札在老宅暗格"。林晚取出手札当日，周明德带人围堵；同时她查到自己的血型与苏秀兰并无血缘——"母亲"一直在用命护着一个不属于她的秘密。'
    },
    ending: {
      ep_range: 'E61-E80',
      title: '终局',
      content: '真相公开：苏秀兰以自杀为代价保住证据链，周明德伏法。林晚在母亲墓前烧掉第七封信，正式接手那七名女工的申诉案——从"为母复仇"转向"为众人发声"，完成人物弧光闭环。'
    }
  },
  clues: [
    { id: 'CLUE_001', name: '第七封信（死后寄出）', tag: '核心', buried_ep: 'E01', resolved_ep: 'E10' },
    { id: 'CLUE_002', name: '苏秀兰手札与老宅暗格', tag: '核心', buried_ep: 'E03', resolved_ep: 'E46' },
    { id: 'CLUE_003', name: '血型不符（非亲生）', tag: '长线', buried_ep: 'E12', resolved_ep: 'E71' },
    { id: 'CLUE_004', name: '周行母亲亦死于火灾', tag: '中期', buried_ep: 'E03', resolved_ep: 'E38' }
  ],
  audience_analysis: {
    target_audience: '25-40 岁女性为主（占比约 68%），下沉市场与一二线并重；偏好"悬念 + 亲情 + 复仇"，对"母亲牺牲"类情感母题敏感度高；日均碎片时长 30-60 分钟，竖屏单集耐受 60-90 秒。',
    paywall_drivers: [
      { name: '悬念钩子', score: 92 },
      { name: '情绪代偿', score: 88 },
      { name: '身份反转', score: 84 },
      { name: '爽点密度', score: 76 },
      { name: '视觉奇观', score: 52 }
    ],
    paywall_episodes: [
      { episode: 10, reason: '第七封信隐形字曝光' },
      { episode: 15, reason: '血型报告疑云' },
      { episode: 20, reason: '周行真实身份反水' },
      { episode: 46, reason: '手札暗格开启' }
    ],
    commercial_positioning: '都市悬疑 · 亲情复仇 · 强钩子连续剧；对标同期同题材 TOP10，差异化在于"母职牺牲"的情感内核与每 5 集一反转的密度。'
  },
  emotion_rhythm: {
    selected_curve: '虐后爽 · 阶梯上升',
    curve_options: ['虐后爽 · 阶梯上升', '持续高压', '先扬后抑', '波浪递进', '低开高走'],
    rhythm_phases: [
      { ep_range: 'E01-E10', title: '建置与钩子', desc: '单集 90s | 前 3 秒特写钩子 | 每集片尾卡点' },
      { ep_range: 'E11-E30', title: '对抗与升级', desc: '打压-反打压交替 | 每 2 集一爽点 | 5 集一中反转' },
      { ep_range: 'E31-E60', title: '真相与崩塌', desc: '信息差收束 | 虐点密集 | 付费卡点 15/20 集中此段' },
      { ep_range: 'E61-E80', title: '清算与归宿', desc: '爽点释放 | 伏笔集中回收 | 长尾转口碑' }
    ]
  }
})

// 阶段 2：故事圣经与世界观完整数据模型
const isEditingBible = ref(false)
const savingBible = ref(false)
const regeneratingBible = ref(false)
const extractingProps = ref(false)
const activeCharTab = ref('林晚')
const currentRelationTimeEp = ref('E20')

const bibleData = ref({
  hitl_passed: true,
  worldview: {
    iron_rules: [
      { id: '01', name: '绝对因果律', desc: '每一个谎言必须由另一个代价更高的谎言来掩盖；凡被隐藏的秘密，必以最残酷的方式在阳光下曝光。' },
      { id: '02', name: '封闭信息茧房', desc: '小镇二十年前的火灾是所有人的禁忌；任何试图打破沉默的人，都会遭受来自宗族与资本的双重围剿。' },
      { id: '03', name: '阶层固化法则', desc: '底层打工人的命在豪门眼中只是可被财报抹平的损耗数字；唯有手握铁证者方能撕开权力裂缝。' }
    ],
    social_hierarchy: {
      layers: [
        { name: '顶层掌控者（周氏宗族）', percent: 10, desc: '掌控全镇命脉、媒体与司法暗流', color: '#f59e0b' },
        { name: '中层共谋/沉默者（管理层/老员工）', percent: 25, desc: '知晓内情却为自保保持缄默', color: '#3b82f6' },
        { name: '底层受害者（遇难女工家属）', percent: 65, desc: '二十年来背负污名与贫困苦苦挣扎', color: '#6b7280' }
      ]
    },
    core_conflict: {
      title: '核心矛盾',
      desc: '孤身寻母真相的女记者 VS 盘根错节的宗族豪门罪恶 —— 在血缘欺骗与正义救赎之间，撕开二十年伪造的意外火灾真相。'
    }
  },
  characters: [
    {
      id: 'C01',
      name: '林晚',
      role_tag: '主角 · 调查记者',
      role_type: 'protagonist',
      avatar: '👩',
      seed: 884213,
      nine_dimensions: {
        mask: '理性冷峻、公事公办的省报调查记者',
        true_self: '内心极度缺乏安全感、执着寻找母亲认可的孤女',
        visual_anchor: '深色风衣 · 便携录音笔 · 银色怀表',
        desire: '查清母亲苏秀兰死亡真相，为火灾遇难者昭雪',
        weakness: '过分执着真相，有时会忽视自身危险与他人善意',
        secret: '并非苏秀兰亲生女儿，血型报告揭晓惊天身世',
        fear: '发现母亲生前对自己的一切爱意都是出于愧疚与任务',
        moral_line: '绝不伪造证据，绝不退缩妥协',
        arc: '从单纯为母复仇 → 扛起七名女工冤案，成为为众人发声的执炬者'
      }
    },
    {
      id: 'C02',
      name: '周衍',
      role_tag: '男主 · 刑警',
      role_type: 'protagonist',
      avatar: '👮‍♂️',
      seed: 519077,
      nine_dimensions: {
        mask: '玩世不恭、按章办事的基层刑警',
        true_self: '隐忍布局二十年、甘愿背负骂名的复仇者',
        visual_anchor: '黑色皮夹克 · 眉骨处浅疤 · 打火机',
        desire: '找出周家当年纵火真凶，替母亲洗刷冤屈',
        weakness: '背负周家血脉的道德原罪与自我厌恶',
        secret: '一直在暗中保护林晚，且手握周氏半本隐秘账册',
        fear: '林晚查到最后发现他是周家私生子而决裂',
        moral_line: '不越过法律红线伤及无辜',
        arc: '从孤狼复仇者 → 与林晚并肩作战，亲手将生父送上审判席'
      }
    },
    {
      id: 'C03',
      name: '周明德',
      role_tag: '反派 · 周氏董事长',
      role_type: 'antagonist',
      avatar: '👴',
      seed: 302914,
      nine_dimensions: {
        mask: '德高望重、热心慈善的知名企业家',
        true_self: '极度冷血、视人命如草芥的家族独裁者',
        visual_anchor: '定制暗纹唐装 · 沉香木手串 · 金丝眼镜',
        desire: '掩盖二十年前火灾真相，保全周氏商业帝国上市',
        weakness: '极度迷信宗族香火与血缘传承',
        secret: '当年为了骗取巨额保险金亲手下令锁死车间安全门',
        fear: '当年被烧死女工的索命手札现世',
        moral_line: '只要能保住家族利益，无人不可牺牲',
        arc: '从不可一世的权力顶峰 → 阴谋彻底败露，中风瘫痪在法庭'
      }
    },
    {
      id: 'C04',
      name: '苏秀兰',
      role_tag: '灵魂人物 · 母亲',
      role_type: 'key',
      avatar: '👵',
      seed: 107662,
      nine_dimensions: {
        mask: '懦弱胆小、患病早逝的老会计',
        true_self: '用二十年隐忍织就绝杀证据网的悲壮守护者',
        visual_anchor: '藏青色毛线开衫 · 锈蚀铁盒 · 绝笔信信封',
        desire: '保全林晚平安长大，同时在死后引爆证据链',
        weakness: '对当年未能救出工友抱有终生愧疚',
        secret: '以自杀伪装意外，将第七封信与绝密手札作为死亡陷阱',
        fear: '林晚在羽翼未丰前被周家灭口',
        moral_line: '宁可牺牲自己生命，绝不向恶势力低头',
        arc: '虽死犹生，通过七封遗信远程主导全剧悬念与反击节奏'
      }
    }
  ],
  relationship_graph: {
    timeline_nodes: ['E01', 'E10', 'E20', 'E46', 'E80'],
    current_ep: 'E20',
    relations_by_ep: {
      'E01': [
        { from: '苏秀兰', to: '林晚', label: '母女 / 遗信托付', type: 'family', desc: '母亲头七寄出绝笔信' },
        { from: '周衍', to: '林晚', label: '警惕 / 试探调查', type: 'suspect', desc: '刑警身份介入老宅' },
        { from: '周明德', to: '林晚', label: '监视 / 施压逼退', type: 'hostile', desc: '周家派人暗中盯梢' },
        { from: '周明德', to: '周衍', label: '父子 / 疏离提防', type: 'family_conflict', desc: '豪门私生子暗流' }
      ],
      'E10': [
        { from: '苏秀兰', to: '林晚', label: '母女 / 暗格指引', type: 'family', desc: '信纸显影手札藏匿点' },
        { from: '周衍', to: '林晚', label: '试探 / 共享疑案', type: 'ally', desc: '周衍透露母亲火灾真相' },
        { from: '周明德', to: '林晚', label: '警告 / 制造阻力', type: 'hostile', desc: '封锁火灾旧档案' },
        { from: '周明德', to: '周衍', label: '试探 / 警务施压', type: 'family_conflict', desc: '勒令周衍调离案件' }
      ],
      'E20': [
        { from: '苏秀兰', to: '林晚', label: '守护 / 身世疑云', type: 'family', desc: '发现非亲生证据' },
        { from: '周衍', to: '林晚', label: '盟友 / 互换线索', type: 'ally', desc: '确认共同敌人周明德' },
        { from: '周明德', to: '林晚', label: '绞杀 / 销毁账本', type: 'hostile', desc: '制造车祸威胁' },
        { from: '周明德', to: '周衍', label: '对立 / 夺权逼宫', type: 'hostile', desc: '周衍暗中扣押账本' }
      ],
      'E46': [
        { from: '苏秀兰', to: '林晚', label: '悲壮 / 遗志传承', type: 'family', desc: '手札密码开启，真相大白' },
        { from: '周衍', to: '林晚', label: '生死相托 / 联手御敌', type: 'ally', desc: '老宅暗道掩护突围' },
        { from: '周明德', to: '林晚', label: '穷凶极恶 / 围堵老宅', type: 'hostile', desc: '周明德带人硬抢手札' },
        { from: '周明德', to: '周衍', label: '彻底反目 / 拔枪对峙', type: 'hostile', desc: '父子关系彻底破裂' }
      ],
      'E80': [
        { from: '苏秀兰', to: '林晚', label: '母爱升华 / 洗冤归宿', type: 'family', desc: '墓前烧信，完成救赎' },
        { from: '周衍', to: '林晚', label: '生死同盟 / 终成眷属', type: 'ally', desc: '法庭并肩公审' },
        { from: '周明德', to: '林晚', label: '法网审判 / 彻底崩溃', type: 'hostile', desc: '周明德伏法获刑' },
        { from: '周明德', to: '周衍', label: '彻底决裂 / 亲手送审', type: 'hostile', desc: '断绝父子血缘关系' }
      ]
    }
  },
  props_library: {
    stats: { extracted_count: 3, total_props: 3, hit_fragments_count: 9 },
    items: [
      {
        id: 'P01',
        name: '第七封绝笔信',
        tag: '核心信物',
        desc: '苏秀兰生前寄出的最后一封信，内含「别查周家」与隐形字',
        fragments: [
          { ep: 'E01', text: '林晚在灵堂供桌下方抠出一只厚实的牛皮纸信封，上面赫然写着：囡囡，别查周家。' },
          { ep: 'E10', text: '火光映照下，信纸背面逐渐显现出暗红色的字迹：手札在老宅西厢暗格。' }
        ],
        visual_prompt: '略带泛黄做旧的牛皮纸信封，封口有蜡封痕迹，上面用毛笔楷书写着「囡囡，别查周家」，电影质感特写，微距景深',
        extract_candidate: '牛皮纸信封特写，墨迹干涸，微距镜头，景深虚化',
        status: 'accepted'
      },
      {
        id: 'P02',
        name: '老宅暗格手札',
        tag: '铁证账册',
        desc: '苏秀兰记录二十年前火灾封门真相与七名女工名单的绝密笔记本',
        fragments: [
          { ep: 'E03', text: '母亲常年在床头摩挲的黑皮笔记本，每一页都浸透了汗渍与泪痕。' },
          { ep: 'E46', text: '林晚从暗格中捧出用油布包裹的厚重手札，翻开第一页便是周明德的亲笔签字。' }
        ],
        visual_prompt: '黑色磨砂皮质旧笔记本，边缘磨损严重，被油布层层包裹，内页密密麻麻记录着日期与火灾排班表，侧光质感',
        extract_candidate: '黑皮手札特写，油布包裹，复古质感，电影光影',
        status: 'accepted'
      },
      {
        id: 'P03',
        name: '二十年前银色怀表',
        tag: '情感锚点',
        desc: '火灾现场遗留的怀表，表盖内嵌有遇难女工当年的合影',
        fragments: [
          { ep: 'E15', text: '周行从内袋掏出一枚严重烧焦但仍走动的机械怀表，表盘定格在午夜两点十七分。' }
        ],
        visual_prompt: '复古雕花纯银机械怀表，表面有轻微火烧焦痕，表盖弹开露出一张泛黄黑白合影，暖调特写光',
        extract_candidate: '烧痕银色怀表特写，微距定格两点十七分',
        status: 'accepted'
      }
    ]
  },
  music_bible: {
    overall_style: '深沉大提琴独奏铺垫悬疑冷感，辅以紧促弦乐跳弓强化信息差对抗；高潮反转引入宏大交响打击乐与电音音浪，全剧 65-135 BPM。',
    motifs: [
      { id: 'm1', name: '绝笔溯源动机', color: '#3b82f6', instruments: '独奏大提琴 + 极简钢琴单音', emotion: '凄凉 · 悬疑 · 追问', episodes: 'E01 / E10 / E46 / E80', bpm: '65-75 BPM' },
      { id: 'm2', name: '暗流交锋动机', color: '#f59e0b', instruments: '急促小提琴跳弓 + 钟摆低音鼓', emotion: '紧迫 · 危机 · 博弈', episodes: 'E05 / E20 / E38 / E60', bpm: '95-108 BPM' },
      { id: 'm3', name: '至暗深渊动机', color: '#ef4444', instruments: '重低音铜管 + 警报电子音效', emotion: '绝望 · 压迫 · 窒息', episodes: 'E15 / E30 / E50 / E71', bpm: '110-120 BPM' },
      { id: 'm4', name: '破晓终局动机', color: '#10b981', instruments: '全编制管弦乐 + 战鼓爆发', emotion: '爽感 · 释怀 · 升华', episodes: 'E75 / E78 / E80', bpm: '125-135 BPM' }
    ],
    bpm_rules: '全剧 65-135 BPM，单集内严格把控情绪转折点，打脸反转前 0.5 秒短暂抽离背景音以提升冲击力。'
  }
})

// 计算当前选中的九维人物与关系网
const currentChar = computed(() => {
  return bibleData.value.characters?.find(c => c.name === activeCharTab.value) || bibleData.value.characters?.[0]
})

const currentRelations = computed(() => {
  const byEp = bibleData.value.relationship_graph?.relations_by_ep || {}
  return byEp[currentRelationTimeEp.value] || byEp['E20'] || []
})

// 阶段 3：三级大纲与分集节拍完整数据模型
const isEditingOutline = ref(false)
const savingOutline = ref(false)
const regeneratingOutline = ref(false)
const validatingOutline = ref(false)

const outlineData = ref({
  hitl_passed: true,
  two_level_acts: [
    {
      act_num: 1,
      title: '破局篇',
      ep_range: 'E01-20',
      ep_count: '20 集',
      target: '确认母亲非自杀，找到第一个可被追查的线索',
      main_conflict: '林晚 VS 家族沉默（与外部压力的初次碰撞）',
      clues: '第七封信的落款日期悖论',
      emotion_base: 'E30 关键证人翻供，前期努力归零',
      emotion_score: 62
    },
    {
      act_num: 2,
      title: '交锋篇',
      ep_range: 'E21-40',
      ep_count: '20 集',
      target: '提升二十年前火灾的完整证据链，迫使周家正面应对',
      main_conflict: '林晚 + 周衍 VS 周明德（结盟与利用的灰色地带）',
      clues: '质检报告底稿与会计双重账本',
      emotion_base: '假证据曝光，信任濒临破碎',
      emotion_score: 78
    },
    {
      act_num: 3,
      title: '危机篇',
      ep_range: 'E41-60',
      ep_count: '20 集',
      target: '老宅暗格手札被夺，血缘秘密被反噬曝光',
      main_conflict: '林晚内心崩塌 VS 周氏反扑围剿',
      clues: '手札密码与身世检验单',
      emotion_base: '至暗时刻，母亲牺牲真相大白',
      emotion_score: 92
    },
    {
      act_num: 4,
      title: '终极篇',
      ep_range: 'E61-80',
      ep_count: '20 集',
      target: '法庭公审清算，为七名女工和母亲洗冤',
      main_conflict: '正义法网 VS 宗族特权',
      clues: '所有伏笔闭环回收',
      emotion_base: '爽感彻底爆发，大仇得报',
      emotion_score: 98
    }
  ],
  three_level_beats: [
    {
      episode_num: 1,
      main_scene: '苏家灵堂',
      core_action: '林晚深夜奔丧，长镜头扫过遗像与白烛',
      reversal: '—',
      ending_cliffhanger: '供桌下露出一角信纸',
      commercial_tag: '情绪爆点',
      status: '已生成'
    },
    {
      episode_num: 3,
      main_scene: '苏家灵堂',
      core_action: '撕开第七封信，读到最后一句话托',
      reversal: '信是母亲死前三天写好的',
      ending_cliffhanger: '落款日期是死后第三天',
      commercial_tag: '核心付费卡点',
      status: '已生成'
    },
    {
      episode_num: 5,
      main_scene: '周氏工厂废墟',
      core_action: '偷拍残存车间，发现被封死的第二安全门',
      reversal: '—',
      ending_cliffhanger: '墙上"安全生产"标语只剩半截',
      commercial_tag: '常规剧情集',
      status: '已生成'
    },
    {
      episode_num: 10,
      main_scene: '老宅暗格',
      core_action: '信纸透光显出暗格位置',
      reversal: '手札真实存在',
      ending_cliffhanger: '暗道机关被触动，火光再现！',
      commercial_tag: '核心付费卡点',
      status: '已生成'
    }
  ],
  main_scenes_pool: [
    { percent: '26%', name: '苏家灵堂', desc: '奔丧 / 对峙 / 归宿，全剧首尾呼应', weight: 26 },
    { percent: '34%', name: '老宅长廊', desc: '发现信物、暗格取证的主要空间', weight: 34 },
    { percent: '18%', name: '周氏工厂废墟', desc: '旧案回溯与视觉奇观', weight: 18 },
    { percent: '14%', name: '周氏宗祠', desc: '宗族势力的权力象征', weight: 14 },
    { percent: '5%', name: '报社', desc: '职业线与信息渠道', weight: 5 },
    { percent: '3%', name: '警局', desc: '卷宗与官方线', weight: 3 }
  ],
  validation_checks: [
    { id: 'hook_coverage', label: '断章钩子 100% 覆盖', passed: true, value: '100%' },
    { id: 'paywall_count', label: '付费卡点 ≥ 4 个', passed: true, value: '(14)' },
    { id: 'paywall_interval', label: '卡点间隔 ≤ 15 集', passed: true, value: '(10)' },
    { id: 'reversal_density', label: '反转密度 ≥ 25%', passed: true, value: '≥ 25%' },
    { id: 'scenes_limit', label: '主场景 ≤ 6 个', passed: true, value: '(4)' }
  ]
})

// 阶段预览数据
const stage1Data = ref({})
const charactersList = ref([])
const outlinesList = ref([])
const selectedEpisodeIndex = ref(3)
const currentScriptContent = ref(`△ 开场特写（前3秒钩子）：
一只骨节分明的手将刻有龙纹的金卡拍在大理石茶几上，震飞红酒杯！

△ 顾沉舟眼神冷漠扫视全场，周身威压骤升。
△ 保镖队长瞳孔猛缩，踉跄倒退三步，冷汗直流。
△ 日 内 顾氏集团顶层总裁办 内灯光闪烁，气氛瞬间降至冰点。

顾沉舟（低沉冷笑）：看来江城这片地界，已经忘了谁才是真正的主人。
林浅（不可置信地看着金卡）：你...你到底是谁？这卡全天下只有三张！

【片尾定格与悬念钩子】
△ 特写定格：保镖队长颤抖跪地，掏出对讲机狂喊家主亲临！
【字幕悬念】：下一集，三大家族族长携千亿资产跪迎龙王！`)

const currentEpisodeId = computed(() => {
  const eps = drama.value?.episodes || []
  return eps[selectedEpisodeIndex.value - 1]?.id || eps[0]?.id || null
})

const currentEpisodeTitleDisplay = computed(() => {
  return `第 03 集 · 灵堂里的第七封信`
})

const currentEpisodeTag = computed(() => {
  return '付费卡点'
})

// ================= 阶段 4：故事剧本三栏工坊核心数据与方法 =================
const currentEpisodeNumber = ref(3)
const episodeSearchKeyword = ref('')
const loadingEpisodeDetail = ref(false)
const regeneratingEpisode = ref(false)
const continuingEpisode = ref(false)
const batchGenerating = ref(false)
const addEpisodeDialogVisible = ref(false)
const addingSingleEpisode = ref(false)

const addEpisodeForm = ref({
  episode_number: 8,
  title: '',
  commercial_tag: '常规剧情集',
  description: '',
  duration: 90
})

// 默认分集导航单元数据
const episodesNavUnits = ref([
  {
    unit_index: 1,
    title: '单元一 · 绝笔信 (01-07 集)',
    paywall_label: '免费钩子',
    episodes: [
      { episode_number: 1, title: '第 01 集 · 迟到的绝笔', score: '94', badge: '', generated: true, scenes_count: 3 },
      { episode_number: 2, title: '第 02 集 · 老宅的锁', score: '91', badge: '', generated: true, scenes_count: 3 },
      { episode_number: 3, title: '第 03 集 · 灵堂里的第七封信', score: '92', badge: '', generated: true, scenes_count: 4 },
      { episode_number: 4, title: '第 04 集 · 迷雾中的影子', score: '88', badge: '', generated: true, scenes_count: 3 },
      { episode_number: 5, title: '第 05 集 · 谁在撒谎', score: '89', badge: '', generated: true, scenes_count: 3 },
      { episode_number: 6, title: '第 06 集 · 危险的试探', score: '90', badge: '并发', generated: true, scenes_count: 3 },
      { episode_number: 7, title: '第 07 集 · 撕裂的伪装', score: '93', badge: '', generated: true, scenes_count: 4 }
    ]
  },
  {
    unit_index: 2,
    title: '单元二 · 迷雾深锁 (08-17 集)',
    paywall_label: '首个付费卡点 E10',
    episodes: [
      { episode_number: 8, title: '第 08 集 · 隐秘暗格', score: '', badge: '', generated: false, scenes_count: 3 },
      { episode_number: 9, title: '第 09 集 · 账本密码', score: '', badge: '', generated: false, scenes_count: 3 },
      { episode_number: 10, title: '第 10 集 · 火海真相', score: '', badge: '', generated: false, scenes_count: 4 }
    ]
  }
])

// 格式化分集序号
function formatEpNum(num) {
  return String(num || 1).padStart(2, '0')
}

// 状态圆点颜色
function epDotClass(ep) {
  if (ep.score && Number(ep.score) >= 90) return 'dot-green'
  if (ep.score && Number(ep.score) < 90) return 'dot-orange'
  if (ep.generated) return 'dot-green'
  return 'dot-gray'
}

// 模糊搜索过滤后的分集单元列表
const filteredUnits = computed(() => {
  const kw = episodeSearchKeyword.value.trim().toLowerCase()
  if (!kw) return episodesNavUnits.value

  const result = []
  for (const unit of episodesNavUnits.value) {
    const matchedEpisodes = unit.episodes.filter(ep => {
      const matchTitle = (ep.title || '').toLowerCase().includes(kw)
      const matchNum = String(ep.episode_number).includes(kw)
      return matchTitle || matchNum
    })
    if (matchedEpisodes.length > 0) {
      result.push({
        ...unit,
        episodes: matchedEpisodes
      })
    }
  }
  return result
})

// 当前查看集的 AST 4 分块与完整质检详情数据
const currentEpisodeDetail = ref({
  episode_num: 3,
  title: '灵堂里的第七封信',
  commercial_tag: '付费卡点前哨',
  qa_score: 92,
  scenes: 4,
  characters: 2,
  props: 2,
  ast_blocks: {
    block1: {
      shots: [
        { type: '特写', text: '林晚泛白的手指死死抠住供桌下方暗格夹层，指甲崩裂渗血。' },
        { type: '快切', text: '微距镜头推至牛皮纸信封，泛黄墨迹赫然写着：<span class="highlight-action">「囡囡，别查周家」</span>。' }
      ]
    },
    block2: {
      shots: [
        { type: '全景环绕', text: '破败的老宅灵堂内，白幡在穿堂冷风中狂乱翻飞，蜡烛骤然熄灭两盏。' },
        { type: '中景动作', text: '周行悄无声息出现在门槛阴影处，右手虚搭在后腰枪套上，冷眼注视林晚的动作。' }
      ]
    },
    block3: {
      patched: true,
      dialogues: [
        { role: '周行', action: '缓步逼近，语气森冷', text: '苏记者的手伸得这么长，真不怕摸到不该摸的东西？' },
        { role: '林晚', action: '迅速将信反扣在掌心，冷笑', text: '周警官踩着我母亲的头七登门，究竟是来吊唁，还是来销毁证物？' },
        { role: '周行', action: '停步，眼神微颤', text: '你以为死在这场火里的，只有你母亲一个人吗？' }
      ]
    },
    block4: {
      patched: true,
      shots: [
        { type: '定格震颤', text: '周行掏出烧焦一半的银色怀表，表盘定格在二十年前火灾同一时刻！' },
        { type: '字幕悬念', text: '【字幕悬念】：他究竟是敌是友？第七封信里的血指印又是谁留下的？！' }
      ]
    }
  },
  metrics: {
    word_count: 1286,
    tokens: 2140,
    model: 'Claude 3.5 Sonnet',
    duration_sec: 18.4,
    auto_heal_round: '1 / 3',
    version_cursor: '#47'
  },
  qa_patches: [
    { id: 'patch_1', tag: '对白潜台词修补', type: 'dialogue', title: '块3 · 对白潜台词修补已合流', desc: '原句「你不要查了」过于直白，已通过 AST 重构为「周记者的手伸得这么长...」' },
    { id: 'patch_2', tag: '片尾断章定格修补', type: 'cliffhanger', title: '块4 · 片尾断章定格修补已合流', desc: '原结尾情绪下滑，已替换为怀表微距定格与字幕钩子' }
  ],
  character_info_gaps: [
    { name: '林晚', known: '信封字迹为母亲亲笔，知晓周行到场', unknown: '周行母亲亦死于当年火灾' },
    { name: '周行', known: '林晚手中掌握账本线索，当年火灾真相', unknown: '第七封信背面暗藏隐形字' }
  ]
})

// 加载分集导航列表
async function loadEpisodesNavigation() {
  if (!dramaId.value) return
  try {
    const res = await scriptStudioAPI.getEpisodesList(dramaId.value)
    if (res?.units && res.units.length > 0) {
      episodesNavUnits.value = res.units
    }
  } catch (e) {
    console.warn('加载分集导航列表失败，使用默认列表:', e)
  }
}

// 加载单集详情与 AST 结构
async function loadEpisodeDetail(epNum) {
  if (!dramaId.value || !epNum) return
  loadingEpisodeDetail.value = true
  try {
    const res = await scriptStudioAPI.getEpisodeDetail(dramaId.value, epNum)
    if (res?.episode) {
      currentEpisodeDetail.value = res.episode
      currentEpisodeNumber.value = res.episode.episode_num || epNum
    }
  } catch (e) {
    console.warn(`加载第 ${epNum} 集详情失败:`, e)
  } finally {
    loadingEpisodeDetail.value = false
  }
}

// 选中分集
function selectEpisode(epNum) {
  currentEpisodeNumber.value = epNum
  selectedEpisodeIndex.value = epNum
  loadEpisodeDetail(epNum)
}

// 重新生成单集剧本
async function onRegenerateSingleEp(epNum) {
  if (!dramaId.value) return
  try {
    await ElMessageBox.confirm(`确定重新生成第 ${formatEpNum(epNum)} 集剧本？将重新执行 4 分块生成与 5 阶闭环质检。`, '重新生成单集', {
      confirmButtonText: '确定重构',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  regeneratingEpisode.value = true
  try {
    const res = await scriptStudioAPI.regenerateEpisodeScript(dramaId.value, epNum)
    ElMessage.success(`第 ${formatEpNum(epNum)} 集剧本重构完成！质检得分: ${res?.episode?.qa_score || 92}`)
    if (res?.episode) {
      currentEpisodeDetail.value = res.episode
      currentEpisodeNumber.value = epNum
    }
    await loadEpisodesNavigation()
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '单集重新生成失败')
  } finally {
    regeneratingEpisode.value = false
  }
}

// 从本集起续写后续剧本
async function onContinueFromEp(epNum) {
  if (!dramaId.value) return
  try {
    await ElMessageBox.confirm(`确定从第 ${formatEpNum(epNum)} 集起向后连续生成？`, '从本集起续写', {
      confirmButtonText: '确定续写',
      cancelButtonText: '取消',
      type: 'primary'
    })
  } catch {
    return
  }

  continuingEpisode.value = true
  try {
    await scriptStudioAPI.continueFromEpisode(dramaId.value, epNum)
    ElMessage.success(`已从第 ${formatEpNum(epNum)} 集起分发 Worker 续写流水线！`)
    await loadEpisodesNavigation()
  } catch (e) {
    ElMessage.error(e.message || '续写任务启动失败')
  } finally {
    continuingEpisode.value = false
  }
}

// 批量生成分集
async function onBatchGenerate(startEp, endEp, count) {
  if (!dramaId.value) return
  batchGenerating.value = true
  try {
    const res = await scriptStudioAPI.batchGenerateEpisodes(dramaId.value, {
      start_ep: startEp,
      end_ep: endEp,
      count: count || (endEp - startEp + 1)
    })
    ElMessage.success(res?.message || `已分发第 ${startEp}-${endEp} 集并发生成任务！`)
    await loadEpisodesNavigation()
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '批量生成失败')
  } finally {
    batchGenerating.value = false
  }
}

// 快捷生成下一批 (3集)
async function onBatchGenerateNext3() {
  const currentTotal = generatedCount.value || 7
  const startEp = currentTotal + 1
  const endEp = Math.min(totalCount.value, currentTotal + 3)
  await onBatchGenerate(startEp, endEp, 3)
}

// 打开新增单集弹窗
function openAddEpisodeDialog() {
  const total = totalCount.value || 80
  const currentGenerated = generatedCount.value || 7
  const nextNum = Math.max(currentGenerated + 1, (episodesNavUnits.value.reduce((max, u) => Math.max(max, ...u.episodes.map(e => e.episode_number)), 0) + 1))
  addEpisodeForm.value = {
    episode_number: nextNum,
    title: `第 ${formatEpNum(nextNum)} 集 · 隐秘交锋`,
    commercial_tag: '常规剧情集',
    description: '',
    duration: 90
  }
  addEpisodeDialogVisible.value = true
}

// 确认新增单集
async function confirmAddSingleEpisode() {
  if (!dramaId.value) return
  if (!addEpisodeForm.value.title.trim()) {
    ElMessage.warning('请填写集标题')
    return
  }

  addingSingleEpisode.value = true
  try {
    const res = await scriptStudioAPI.addSingleEpisode(dramaId.value, addEpisodeForm.value)
    ElMessage.success(`第 ${formatEpNum(addEpisodeForm.value.episode_number)} 集已成功创建！`)
    addEpisodeDialogVisible.value = false
    await loadEpisodesNavigation()
    if (res?.episode?.episode_number) {
      selectEpisode(res.episode.episode_number)
    }
  } catch (e) {
    ElMessage.error(e.message || '新增单集失败')
  } finally {
    addingSingleEpisode.value = false
  }
}

// 默认占位数据
const defaultCharacters = [
  { name: '林晚', role: 'protagonist', identity_and_mask: '调查母亲死因的敏锐女记者', visual_anchor: '深色风衣，短发，随身携带录音笔' },
  { name: '周行', role: 'supporter', identity_and_mask: '追查当年火灾真相的刑警', visual_anchor: '皮夹克，眼神深邃锐利' },
  { name: '周震天', role: 'antagonist', identity_and_mask: '周氏集团掌门人，幕后真凶', visual_anchor: '定制唐装，右手持两枚沉香手串' }
]

const defaultOutlines = [
  { episode_num: 1, title: '第七封遗信', commercial_tag: '免费引流钩子', core_action: '林晚在老宅拆开染血信封', ending_cliffhanger: '门外突然传来敲门声' },
  { episode_num: 2, title: '深夜造访的刑警', commercial_tag: '免费引流钩子', core_action: '周行亮明证件与母辈旧事', ending_cliffhanger: '周氏工厂照片浮出水面' },
  { episode_num: 3, title: '灵堂里的第七封信', commercial_tag: '核心付费卡点', core_action: '两人联手潜入老宅密室', ending_cliffhanger: '暗道机关被触动，火光再现！' }
]

function stagePassed(stageKey) {
  if (stageKey === 'stage1') return Boolean(stage1Data.value?.title || stage1Data.value?.one_sentence_hook)
  if (stageKey === 'stage2') return Boolean(charactersList.value && charactersList.value.length > 0)
  if (stageKey === 'stage3') return Boolean(outlinesList.value && outlinesList.value.length > 0)
  if (stageKey === 'stage4') return generatedCount.value > 0
  if (stageKey === 'stage5') return Boolean(drama.value?.lock_status === 1 || drama.value?.pipeline_status === 'completed')
  return false
}

function changeEpisodes(delta) {
  const newVal = episodeCount.value + delta
  if (newVal >= 5 && newVal <= 120) {
    episodeCount.value = newVal
    totalCount.value = newVal
  }
}

// 切换查看分集剧本
function onEpisodeSelectChange(index) {
  selectedEpisodeIndex.value = index
  const ep = drama.value?.episodes?.find(e => e.episode_number === index)
  if (ep && ep.content) {
    currentScriptContent.value = ep.content
  }
}

// 加载项目详情与各阶段产出
async function loadDramaDetail() {
  if (!dramaId.value) return
  try {
    const res = await dramaAPI.get(dramaId.value)
    drama.value = res
    totalCount.value = res.total_episodes || 80
    episodeCount.value = res.total_episodes || 80
    if (res.description) storyPrompt.value = res.description
    if (res.genre) selectedGenre.value = res.genre

    // 统计资产与角色
    characterCount.value = res.characters?.length || 0
    propCount.value = res.props?.length || 0
    sceneCount.value = res.scenes?.length || 0
    storyboardCount.value = res.storyboards_count || (res.episodes?.length ? res.episodes.length * 4 : 0)

    // 角色列表
    if (res.characters && res.characters.length > 0) {
      charactersList.value = res.characters.map(c => ({
        name: c.name,
        role: c.role || '主要角色',
        role_type: c.role || '主要角色',
        identity_and_mask: c.description || c.identity_anchors || '核心人物',
        visual_anchor: c.appearance || c.identity_anchors || '鲜明视觉识别特征'
      }))
    }

    // 分集与大纲列表
    if (res.episodes && res.episodes.length > 0) {
      outlinesList.value = res.episodes.map(ep => {
        let coreAction = '动作推进，触发剧情高潮'
        let endingCliffhanger = '片尾特写定格与悬念反转'
        if (ep.description) {
          const actionMatch = ep.description.match(/【核心动作】([^\n]+)/)
          const endingMatch = ep.description.match(/【片尾断章】([^\n]+)/)
          if (actionMatch) coreAction = actionMatch[1].trim()
          if (endingMatch) endingCliffhanger = endingMatch[1].trim()
          else if (!actionMatch) coreAction = ep.description.slice(0, 40)
        }
        return {
          episode_num: ep.episode_number,
          title: ep.title || `第${ep.episode_number}集`,
          commercial_tag: ep.commercial_tag || '常规剧情集',
          core_action: coreAction,
          ending_cliffhanger: endingCliffhanger,
          content: ep.content
        }
      })

      // 统计已生成正文的集数
      const generatedEps = res.episodes.filter(ep => ep.content && ep.content.trim().length > 0)
      generatedCount.value = generatedEps.length

      // 刷新当前选中的剧本正文
      const currentEp = res.episodes.find(ep => ep.episode_number === selectedEpisodeIndex.value) || res.episodes[0]
      if (currentEp && currentEp.content) {
        currentScriptContent.value = currentEp.content
      }
    }

    // 解析 metadata 回显扩展表单配置与立项数据
    let meta = res.metadata
    if (typeof meta === 'string') {
      try { meta = JSON.parse(meta) } catch (e) { meta = {} }
    }
    if (meta && typeof meta === 'object') {
      if (meta.story_prompt) storyPrompt.value = meta.story_prompt
      if (meta.type) selectedType.value = meta.type
      if (meta.episode_duration) episodeDuration.value = meta.episode_duration
      if (meta.paywall_episodes) paywallEpisodes.value = meta.paywall_episodes
      if (meta.concurrency_mode) selectedConcurrency.value = meta.concurrency_mode
      if (meta.hitl_strategy) hitlStrategy.value = meta.hitl_strategy
      if (typeof meta.hitl_mode === 'boolean') isHitlEnabled.value = meta.hitl_mode

      if (meta.concept_design && typeof meta.concept_design === 'object') {
        conceptData.value = {
          ...conceptData.value,
          ...meta.concept_design
        }
      }

      if (meta.bible_design && typeof meta.bible_design === 'object') {
        bibleData.value = {
          ...bibleData.value,
          ...meta.bible_design
        }
      }

      if (meta.outline_design && typeof meta.outline_design === 'object') {
        outlineData.value = {
          ...outlineData.value,
          ...meta.outline_design
        }
      }

      if (meta.worldview || meta.target_audience || meta.paywall_driver || meta.one_sentence_hook) {
        stage1Data.value = {
          title: res.title || meta.title || '',
          one_sentence_hook: meta.one_sentence_hook || '',
          story_summary: meta.story_prompt || res.description || '',
          target_audience: meta.target_audience || '25-45岁受众，爽感与强悬念驱动',
          paywall_driver: meta.paywall_driver || '多重绝密身份层层揭晓，极致反差爽点'
        }
      }
    }

    if (res.pipeline_status === 'paused_hitl') {
      isPipelinePaused.value = true
      pipelineRunning.value = false
      pausedNode.value = res.hitl_paused_node || 'outline_generation'
    } else if (res.pipeline_status === 'running') {
      pipelineRunning.value = true
      isPipelinePaused.value = false
    } else {
      pipelineRunning.value = false
      isPipelinePaused.value = false
    }
  } catch (e) {
    console.error('加载短剧详情失败:', e)
  }
}

// 加载全部短剧列表
async function loadAllDramas() {
  try {
    const res = await dramaAPI.list({ page: 1, page_size: 50 })
    allDramas.value = res?.items ?? []
  } catch (e) {
    console.error('加载短剧列表失败:', e)
  }
}

function onDramaChange(newId) {
  router.push(`/drama/${newId}/studio`)
}

// 建立 SSE 实时事件流
function setupEventSource() {
  if (!dramaId.value) return
  if (eventSource) {
    eventSource.close()
  }
  const sseUrl = `/api/v1/script-studio/dramas/${dramaId.value}/events`
  eventSource = new EventSource(sseUrl)

  eventSource.onmessage = async (event) => {
    try {
      const data = JSON.parse(event.data)
      const evtType = data.type || data.event

      if (evtType === 'phase1_completed') {
        ElMessage.success('【阶段 1 创意立项】已完成，高概念方案与受众画像已落库！')
        stage1Data.value = {
          ...stage1Data.value,
          title: data.title || stage1Data.value.title,
          one_sentence_hook: data.one_sentence_hook || stage1Data.value.one_sentence_hook,
          story_summary: data.core_conflict || stage1Data.value.story_summary
        }
        // 自动流转到阶段 2 故事圣经
        activeTab.value = 'stage2_bible'
        await loadDramaDetail()
      } else if (evtType === 'phase2_completed') {
        ElMessage.success(`【阶段 2 故事圣经】已完成，已构建 ${data.character_count || 0} 位九维角色档案！`)
        await loadDramaDetail()
        // 自动流转到阶段 3 三级大纲
        activeTab.value = 'stage3_outline'
      } else if (evtType === 'phase3_completed') {
        ElMessage.success(`【阶段 3 三级大纲】已生成 ${data.outline_count || 0} 集分集微观节拍！`)
        await loadDramaDetail()
        if (isHitlEnabled.value) {
          // 人工审核模式：停留在阶段 3
          activeTab.value = 'stage3_outline'
        } else {
          // 非人工审核模式：流转到阶段 4
          activeTab.value = 'stage4_script'
        }
      } else if (evtType === 'hitl_interrupt') {
        isPipelinePaused.value = true
        pausedNode.value = data.node || 'outline_generation'
        pipelineRunning.value = false
        ElMessage.warning('【HITL 挂起】阶段 3 三级大纲已生成完毕，等待编剧审批确认！')
        activeTab.value = 'stage3_outline'
        await loadDramaDetail()
      } else if (evtType === 'episode_generated') {
        generatedCount.value = Math.min(totalCount.value, (data.episode_num || generatedCount.value + 1))
        ElMessage.info(`第 ${data.episode_num} 集剧本正文生成完毕 (质检分: ${data.qa_score || 90})`)
        await loadDramaDetail()
        if (!isPipelinePaused.value && activeTab.value !== 'stage5_finalize') {
          activeTab.value = 'stage4_script'
        }
      } else if (evtType === 'batch_completed') {
        if (data.completed_episodes && data.completed_episodes.length > 0) {
          generatedCount.value = Math.max(...data.completed_episodes)
        }
        await loadDramaDetail()
      } else if (evtType === 'pipeline_completed') {
        pipelineRunning.value = false
        isPipelinePaused.value = false
        ElMessage.success('全剧剧本工业化流水线已全部生成完毕！')
        await loadDramaDetail()
        if (!isHitlEnabled.value || !isPipelinePaused.value) {
          // 非人工审核模式或已完成全部流程，自动停留在复盘定稿标签页
          activeTab.value = 'stage5_finalize'
        }
      } else if (evtType === 'pipeline_error') {
        pipelineRunning.value = false
        ElMessage.error(`流水线执行异常: ${data.error || '未知错误'}`)
      }
    } catch (e) {
      console.warn('SSE 数据解析异常:', e)
    }
  }

  eventSource.onerror = () => {
    // 降级关闭
  }
}

// 阶段 1：创意立项高概念编辑与操作方法
function startEditConcept() {
  isEditingConcept.value = true
}

// 保存阶段 1 修改
async function saveConcept() {
  if (!dramaId.value) return
  savingConcept.value = true
  try {
    await scriptStudioAPI.saveConceptDesign(dramaId.value, {
      concept_design: conceptData.value
    })
    ElMessage.success('创意立项高概念方案已成功保存！下游节点已自动标记待更新。')
    isEditingConcept.value = false
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '保存立项方案失败')
  } finally {
    savingConcept.value = false
  }
}

// 重新生成阶段 1
async function onRegenerateConcept() {
  if (!dramaId.value) return
  try {
    await ElMessageBox.confirm('重新生成将基于当前故事梗概重新构建高概念与商业分析，是否继续？', '重新生成阶段 1', {
      confirmButtonText: '确定重新生成',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  regeneratingConcept.value = true
  try {
    const res = await scriptStudioAPI.regenerateConcept(dramaId.value, {
      user_prompt: storyPrompt.value || drama.value?.description || '',
      genre: selectedGenre.value,
      type: selectedType.value,
      total_episodes: episodeCount.value
    })
    ElMessage.success('阶段 1 创意立项高概念已重新生成！')
    if (res?.concept_design) {
      conceptData.value = {
        ...conceptData.value,
        ...res.concept_design
      }
    }
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '重新生成失败')
  } finally {
    regeneratingConcept.value = false
  }
}

// 核心伏笔池：新增伏笔
function addClueItem() {
  if (!conceptData.value.clues) {
    conceptData.value.clues = []
  }
  const nextNum = conceptData.value.clues.length + 1
  const idStr = `CLUE_${String(nextNum).padStart(3, '0')}`
  conceptData.value.clues.push({
    id: idStr,
    name: '新增核心伏笔线索',
    tag: '核心',
    buried_ep: 'E01',
    resolved_ep: 'E10'
  })
}

// 核心伏笔池：删除伏笔
function removeClueItem(idx) {
  if (conceptData.value.clues && conceptData.value.clues.length > 0) {
    conceptData.value.clues.splice(idx, 1)
  }
}

// 付费卡点：新增卡点
function addPaywallNode() {
  if (!conceptData.value.audience_analysis) {
    conceptData.value.audience_analysis = {}
  }
  if (!conceptData.value.audience_analysis.paywall_episodes) {
    conceptData.value.audience_analysis.paywall_episodes = []
  }
  conceptData.value.audience_analysis.paywall_episodes.push({
    episode: 25,
    reason: '关键反转卡点'
  })
}

// 付费卡点：删除卡点
function removePaywallNode(idx) {
  if (conceptData.value.audience_analysis?.paywall_episodes) {
    conceptData.value.audience_analysis.paywall_episodes.splice(idx, 1)
  }
}

// 阶段 2：故事圣经与世界观操作方法
function startEditBible() {
  isEditingBible.value = true
}

async function saveBible() {
  if (!dramaId.value) return
  savingBible.value = true
  try {
    await scriptStudioAPI.saveBibleDesign(dramaId.value, {
      bible_design: bibleData.value
    })
    ElMessage.success('故事圣经与人设库已成功保存！')
    isEditingBible.value = false
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '保存故事圣经失败')
  } finally {
    savingBible.value = false
  }
}

async function onRegenerateBible() {
  if (!dramaId.value) return
  try {
    await ElMessageBox.confirm('重新生成将基于当前创意立项重构世界观、人物九维矩阵与配乐设计，是否继续？', '重新生成故事圣经', {
      confirmButtonText: '确定重新生成',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  regeneratingBible.value = true
  try {
    const res = await scriptStudioAPI.regenerateBible(dramaId.value)
    ElMessage.success('阶段 2 故事圣经已重新生成！')
    if (res?.bible_design) {
      bibleData.value = {
        ...bibleData.value,
        ...res.bible_design
      }
    }
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '重新生成失败')
  } finally {
    regeneratingBible.value = false
  }
}

async function onExtractProps() {
  if (!dramaId.value) return
  extractingProps.value = true
  try {
    const res = await scriptStudioAPI.extractProps(dramaId.value)
    ElMessage.success(`已从分集正文中成功抽取 ${res?.extracted_count || 3} 件核心道具视觉 Prompt！`)
    if (res?.props_library) {
      bibleData.value.props_library = res.props_library
    }
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '抽取道具 Prompt 失败')
  } finally {
    extractingProps.value = false
  }
}

// 阶段 3：三级大纲与分集节拍操作方法
function startEditOutline() {
  isEditingOutline.value = true
}

async function saveOutline() {
  if (!dramaId.value) return
  savingOutline.value = true
  try {
    await scriptStudioAPI.saveOutlineDesign(dramaId.value, {
      two_level_acts: outlineData.value.two_level_acts,
      three_level_beats: outlineData.value.three_level_beats,
      main_scenes_pool: outlineData.value.main_scenes_pool
    })
    ElMessage.success('三级大纲与分集节拍已成功保存！')
    isEditingOutline.value = false
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '保存三级大纲失败')
  } finally {
    savingOutline.value = false
  }
}

async function onRegenerateOutline() {
  if (!dramaId.value) return
  try {
    await ElMessageBox.confirm('重新生成将基于当前立项与圣经重构二级四幕与三级分集节拍，是否继续？', '重新生成三级大纲', {
      confirmButtonText: '确定重新生成',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  regeneratingOutline.value = true
  try {
    const res = await scriptStudioAPI.regenerateOutline(dramaId.value)
    ElMessage.success('阶段 3 三级大纲已重新生成！')
    if (res?.outline_design) {
      outlineData.value = {
        ...outlineData.value,
        ...res.outline_design
      }
    }
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '重新生成大纲失败')
  } finally {
    regeneratingOutline.value = false
  }
}

async function onValidateOutline() {
  if (!dramaId.value) return
  validatingOutline.value = true
  try {
    const res = await scriptStudioAPI.validateOutline(dramaId.value)
    if (res?.checks) {
      outlineData.value.validation_checks = res.checks
    }
    ElMessage.success(res?.summary || '大纲工业化 5 项质检指标已全部通过！')
  } catch (e) {
    ElMessage.error(e.message || '大纲质检校验失败')
  } finally {
    validatingOutline.value = false
  }
}

function addBeatItem() {
  if (!outlineData.value.three_level_beats) {
    outlineData.value.three_level_beats = []
  }
  const nextNum = outlineData.value.three_level_beats.length + 1
  outlineData.value.three_level_beats.push({
    episode_num: nextNum,
    main_scene: '苏家灵堂',
    core_action: `第${nextNum}集新增动作与线索`,
    reversal: '—',
    ending_cliffhanger: '剧情悬念定格',
    commercial_tag: '常规剧情集',
    status: '草稿'
  })
}

function removeBeatItem(bIdx) {
  if (outlineData.value.three_level_beats && outlineData.value.three_level_beats.length > 0) {
    outlineData.value.three_level_beats.splice(bIdx, 1)
  }
}

async function confirmAndBatchGenerate() {
  if (isPipelinePaused.value) {
    await onResumePipeline()
  } else {
    ElMessage.success('三级大纲已锁定通过，正在分发 Worker 并发生成分集正文！')
    activeTab.value = 'stage4_script'
  }
}

// 启动 LangGraph 流水线
async function onStartPipeline() {
  if (!storyPrompt.value.trim()) {
    ElMessage.warning('请输入故事核心梗概或用户提示词')
    return
  }
  pipelineRunning.value = true
  // 自动切换到阶段 1
  activeTab.value = 'stage1_concept'
  stage1Data.value = {
    title: drama.value?.title || '剧本工业化创作中...',
    one_sentence_hook: '生成中...',
    story_summary: storyPrompt.value.trim(),
    target_audience: '25-45岁受众，爽感与强悬念驱动',
    paywall_driver: '多重绝密身份层层揭晓，极致反差爽点'
  }

  try {
    const commTag = `${selectedGenre.value}-${selectedType.value}`
    await scriptStudioAPI.startPipeline(dramaId.value, {
      user_prompt: storyPrompt.value.trim(),
      genre: selectedGenre.value,
      type: selectedType.value,
      total_episodes: episodeCount.value,
      episode_duration: episodeDuration.value,
      paywall_episodes: paywallEpisodes.value,
      concurrency_mode: selectedConcurrency.value,
      hitl_strategy: hitlStrategy.value,
      commercial_tag: commTag,
      hitl_mode: isHitlEnabled.value
    })
    ElMessage.success('LangGraph 工业化创作流水线已启动！')
  } catch (e) {
    ElMessage.error(e.message || '启动流水线失败')
    pipelineRunning.value = false
  }
}

// 断点唤醒恢复
async function onResumePipeline() {
  resuming.value = true
  try {
    await scriptStudioAPI.resumePipeline(dramaId.value, {})
    isPipelinePaused.value = false
    pipelineRunning.value = true
    // 人工审核确认后流转到阶段 4 剧本生成
    activeTab.value = 'stage4_script'
    ElMessage.success('已确认大纲，流水线已恢复执行后续分集并发生成！')
  } catch (e) {
    ElMessage.error(e.message || '恢复流水线失败')
  } finally {
    resuming.value = false
  }
}

function onContinueNextBatch() {
  ElMessage.info('正在分发下一批次并发 Worker 生成...')
}

function onSaveCurrent() {
  ElMessage.success('当前集已保存')
}

// 确认定稿并转入视听制作
async function onFinalizeAndBridge() {
  locking.value = true
  try {
    await scriptStudioAPI.lockDrama(dramaId.value)
    await scriptStudioAPI.syncVisual(dramaId.value)
    ElMessage.success('全剧剧本已定稿锁定，已触发 Bridge 契约同步分镜资产！')
    router.push(`/film/${dramaId.value}/canvas`)
  } catch (e) {
    ElMessage.error(e.message || '定稿锁定失败')
  } finally {
    locking.value = false
  }
}

// ================= 阶段 5：复盘定稿与全剧归宿校验核心数据与方法 =================
const loadingFinalizeAudit = ref(false)
const matrixFilterType = ref('all') // all, paywall, reversal, low_score
const selectedMatrixEp = ref(null)
const healDialogVisible = ref(false)
const healingEp = ref(false)
const exportDialogVisible = ref(false)
const exporting = ref(false)
const exportFileList = ref([
  { name: '头七夜的第七封信_全剧80集分集剧本.pdf', size: '18.4 MB', format: 'PDF (带水印排版台本)' },
  { name: '头七夜的第七封信_剧组标准工业化台本.docx', size: '6.2 MB', format: 'Word (含场景/人物分表)' },
  { name: '头七夜的第七封信_320镜头分镜表与Bridge契约.csv', size: '1.8 MB', format: 'CSV (镜头与Seed锚点)' },
  { name: '头七夜的第七封信_AST语义结构化元数据.json', size: '3.5 MB', format: 'JSON (LangGraph状态机)' },
  { name: '头七夜的第七封信_全剧五阶质检与复盘审计报告.pdf', size: '4.1 MB', format: 'PDF (质检雷达与伏笔)' }
])

const finalizeAuditData = ref({
  drama_id: 0,
  drama_title: '头七夜的第七封信',
  commercial_tag: '都市悬疑 · 亲情复仇',
  total_episodes: 80,
  generated_episodes: 80,
  completion_percent: '100%',
  word_count_wan: '18.6 万',
  duration_minutes: '120 分钟',
  qualified_episodes: '77/80',
  version_tag: 'v7.2-final',
  lock_status: 0,
  radar_analytics: {
    overall_health_score: 92.8,
    weights_desc: '五阶满分 100: 结构 25 / 人物 20 / 场景 20 / 台词 20 / 卡点 15',
    low_score_episodes: ['E11', 'E19', 'E64'],
    low_score_count: 3,
    dimensions: [
      { name: '结构节奏', score: 23.4, max: 25, percent: 93.6, color: '#10b981' },
      { name: '人物塑造', score: 18.6, max: 20, percent: 93.0, color: '#10b981' },
      { name: '场景视听', score: 18.2, max: 20, percent: 91.0, color: '#6366f1' },
      { name: '台词对白', score: 17.9, max: 20, percent: 89.5, color: '#6366f1' },
      { name: '商业卡点', score: 14.7, max: 15, percent: 98.0, color: '#10b981' }
    ],
    ast_heal_stats: {
      heal_rounds: 186,
      patched_blocks: 412,
      first_pass_count: 397,
      heal_success_rate: '96.4%',
      tokens_saved_percent: '94%'
    }
  },
  delivery_matrix: {
    total_episodes: 80,
    total_storyboards: 320,
    qualified_count: 77,
    need_patch_count: 3,
    episodes: []
  },
  character_arcs: [
    {
      id: 'char_linwan',
      name: '林晚',
      role_tag: '主角 · 调查记者',
      current_status: '已闭环',
      initial_state: '逃避 · 用职业理性掩盖情感饥饿',
      end_state: '直面 · 为众人发声',
      timeline: [
        { ep: 'E01', text: '麻木 · 例行奔丧' },
        { ep: 'E10', text: '动摇 · 隐形字曝光' },
        { ep: 'E38', text: '崩塌 · 发现被利用' },
        { ep: 'E46', text: '重构 · 非亲生冲击' },
        { ep: 'E61', text: '抉择 · 重新结盟' },
        { ep: 'E80', text: '闭环 · 接手申诉案' }
      ]
    },
    {
      id: 'char_zhouyan',
      name: '周衍',
      role_tag: '男主 · 卧底刑警',
      current_status: '已闭环',
      initial_state: '利用着 · 工具理性',
      end_state: '承担者 · 出庭指证',
      timeline: [
        { ep: 'E03', text: '伪装 · 公事公办' },
        { ep: 'E20', text: '松动 · 共享线索' },
        { ep: 'E38', text: '暴露 · 被识破' },
        { ep: 'E57', text: '赎罪 · 交出钥匙' },
        { ep: 'E71', text: '闭环 · 指证叔父' },
        { ep: 'E80', text: '服刑 · 承担代价' }
      ]
    },
    {
      id: 'char_zhoumingde',
      name: '周明德',
      role_tag: '反派 · 宗族掌权人',
      current_status: '已闭环',
      initial_state: '掌控者 · 体面压倒一切',
      end_state: '溃败者 · 体面彻底破产',
      timeline: [
        { ep: 'E06', text: '压制 · 暗示封口' },
        { ep: 'E20', text: '交锋 · 正面威胁' },
        { ep: 'E46', text: '忌惮 · 搜暗格' },
        { ep: 'E55', text: '反扑 · 全族审判' },
        { ep: 'E78', text: '溃败 · 录音公开' },
        { ep: 'E80', text: '伏法 · 获刑受审' }
      ]
    },
    {
      id: 'char_suxiulan',
      name: '苏秀兰',
      role_tag: '核心引子 · 亡母',
      current_status: '已闭环 (回溯揭示)',
      initial_state: '软弱受害者 · 逆来顺受',
      end_state: '布局者 · 以死换证据链',
      timeline: [
        { ep: 'E01', text: '缺席 · 只有遗像' },
        { ep: 'E10', text: '显影 · 隐形字' },
        { ep: 'E46', text: '揭示 · 手札真意' },
        { ep: 'E49', text: '补充 · 主动认罪' },
        { ep: 'E70', text: '终现 · 当票夹层' },
        { ep: 'E80', text: '告别 · 烧掉第七封信' }
      ]
    }
  ],
  clue_closures: {
    total_clues: 12,
    recovered_count: 9,
    pending_count: 1,
    unrecovered_count: 2,
    recovery_rate: '75.0%',
    items: [
      { id: 'CLUE_001', name: '第七封绝笔信（死后寄出）', buried_ep: 'E01', resolved_ep: 'E10', path_desc: 'E01 灵堂发现 → E10 隐形字曝光', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_002', name: '苏秀兰手札与老宅暗格', buried_ep: 'E03', resolved_ep: 'E46', path_desc: 'E03 发现暗格痕迹 → E46 取出手札原件', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_003', name: '血型不符（非亲生）', buried_ep: 'E12', resolved_ep: 'E71', path_desc: 'E12 验血报告异常 → E71 当庭解开身世', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_004', name: '周行母亲亦死于火灾', buried_ep: 'E03', resolved_ep: 'E38', path_desc: 'E03 怀表线索 → E38 周行坦白家仇', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_005', name: '旧打火机上的「安」字', buried_ep: 'E04', resolved_ep: 'E74', path_desc: 'E04 特写 → E74 质检报告签名同字', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_006', name: '每月封口费流水', buried_ep: 'E28', resolved_ep: 'E78', path_desc: 'E28 账本 → E78 当庭出示', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_007', name: '七名女工工牌', buried_ep: 'E33', resolved_ep: 'E71', path_desc: 'E33 半截工牌 → E66 家属递上 → E71 旁听席', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_008', name: '被水泥封死的安全门', buried_ep: 'E05', resolved_ep: 'E74', path_desc: 'E05 发现 → E74 挖出质检报告原件', status: '已回收', status_type: 'recovered' },
      { id: 'CLUE_009', name: '周明德当年的调令传真', buried_ep: 'E19', resolved_ep: 'E64', path_desc: 'E19 碎纸机残片 → E64 拼合传真', status: '待补全', status_type: 'pending' },
      { id: 'CLUE_010', name: '老宅西厢房的第二把钥匙', buried_ep: 'E08', resolved_ep: '—', path_desc: 'E08 铜锁钥匙埋设 → 暂无回收集数', status: '未回收', status_type: 'unrecovered' },
      { id: 'CLUE_011', name: '更衣室储物柜 07 号锁牌', buried_ep: 'E15', resolved_ep: '—', path_desc: 'E15 柜门线索 → 暂无回收集数', status: '未回收', status_type: 'unrecovered' },
      { id: 'CLUE_012', name: '苏秀兰留下的红色录音带', buried_ep: 'E22', resolved_ep: 'E79', path_desc: 'E22 磁带埋设 → E79 磁带播放', status: '已回收', status_type: 'recovered' }
    ]
  },
  visual_bridge_readiness: {
    storyboards_total: 320,
    shots_per_episode: 4,
    shot_distributions: [
      { type: '特写 CU', percent: '38%', weight: 38, color: '#8b5cf6' },
      { type: '近景 MCU', percent: '27%', weight: 27, color: '#3b82f6' },
      { type: '中景 MS', percent: '19%', weight: 19, color: '#10b981' },
      { type: '全景 WS', percent: '11%', weight: 11, color: '#f59e0b' },
      { type: '大远景 ELS', percent: '5%', weight: 5, color: '#6b7280' }
    ],
    music_cues: [
      { id: 'mc_1', ep: 'E10', action: '隐形字曝光', motif: '真相动机 · 弦乐渐强', bpm: '96 BPM', duration: '8s' },
      { id: 'mc_2', ep: 'E38', action: '身份暴露', motif: '威胁动机 · 心跳采样', bpm: '88 BPM', duration: '6s' },
      { id: 'mc_3', ep: 'E46', action: '非亲生冲击', motif: '母亲动机变奏 · 钢琴单音', bpm: '64 BPM', duration: '12s' },
      { id: 'mc_4', ep: 'E71', action: '出庭指证', motif: '清算动机 · 合唱推进', bpm: '118 BPM', duration: '10s' },
      { id: 'mc_5', ep: 'E78', action: '录音公开', motif: '清算动机 · 鼓组爆发', bpm: '124 BPM', duration: '9s' },
      { id: 'mc_6', ep: 'E80', action: '烧信告别', motif: '母亲动机 · 女声哼鸣收束', bpm: '62 BPM', duration: '16s' }
    ]
  },
  checklist: {
    upstream_passed: true,
    qa_passed: false,
    clues_passed: false,
    health_score_ok: true,
    is_locked: false,
    warning_text: '仍有 2 条伏笔未回收、3 集低于 85 分，建议先处理再定稿'
  }
})

// 根据 Tabs 过滤交付矩阵分集
const filteredMatrixEpisodes = computed(() => {
  const eps = finalizeAuditData.value.delivery_matrix?.episodes || []
  if (eps.length === 0) {
    // 降级生成默认 80 集
    const list = []
    const lowMap = { 11: 79, 19: 74, 64: 81 }
    const paywalls = new Set([10, 15, 20, 25, 30, 40, 50, 60, 70])
    const reversals = new Set([3, 7, 10, 14, 18, 22, 27, 33, 38, 46, 55, 66, 74, 78])
    for (let i = 1; i <= (totalCount.value || 80); i++) {
      const isLow = Boolean(lowMap[i])
      const score = isLow ? lowMap[i] : (90 + (i * 7) % 8)
      const isPay = paywalls.has(i)
      const isRev = reversals.has(i)
      list.push({
        episode_number: i,
        title: `第${i}集`,
        score,
        is_paywall: isPay,
        is_reversal: isRev,
        need_patch: isLow,
        commercial_tag: isPay ? '核心付费卡点' : (isRev ? '高潮反转集' : '常规剧情集')
      })
    }
    return list
  }

  if (matrixFilterType.value === 'paywall') {
    return eps.filter(e => e.is_paywall)
  }
  if (matrixFilterType.value === 'reversal') {
    return eps.filter(e => e.is_reversal)
  }
  if (matrixFilterType.value === 'low_score') {
    return eps.filter(e => e.need_patch || (e.score && e.score < 85))
  }
  return eps
})

// 加载阶段 5 复盘定稿数据
async function loadFinalizeAudit() {
  if (!dramaId.value) return
  loadingFinalizeAudit.value = true
  try {
    const res = await scriptStudioAPI.getFinalizeAudit(dramaId.value)
    if (res) {
      finalizeAuditData.value = {
        ...finalizeAuditData.value,
        ...res
      }
    }
  } catch (e) {
    console.warn('获取阶段 5 复盘数据失败，使用前端默认高保真模型:', e)
  } finally {
    loadingFinalizeAudit.value = false
  }
}

function onSelectMatrixEpisode(ep) {
  selectedMatrixEp.value = ep
  healDialogVisible.value = true
}

// 点击伏笔状态进行快速自愈
async function onClickClueStatus(clue) {
  if (clue.status_type === 'recovered') {
    ElMessage.info(`伏笔 ${clue.id} 已在 ${clue.resolved_ep} 闭环回收`)
    return
  }
  try {
    await ElMessageBox.confirm(
      `伏笔「${clue.name}」(${clue.id}) 当前状态为 ${clue.status}。是否调用 AST 自愈模型在对应剧集中补全回收逻辑？`,
      '伏笔智能自愈补全',
      { confirmButtonText: '确定补全', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  try {
    const res = await scriptStudioAPI.healClue(dramaId.value, {
      clue_id: clue.id,
      recover_episode: 78
    })
    ElMessage.success(res?.message || `伏笔 ${clue.id} 已成功在后续剧集中补全回收！`)
    await loadFinalizeAudit()
  } catch (e) {
    ElMessage.error(e.message || '伏笔自愈失败')
  }
}

// 确认执行分集 AST 局部自愈提分
async function confirmHealEpisode(epNum) {
  healingEp.value = true
  try {
    const res = await scriptStudioAPI.healEpisode(dramaId.value, {
      episode_num: epNum,
      target_score: 93
    })
    ElMessage.success(res?.message || `第 ${formatEpNum(epNum)} 集已成功执行 AST 局部修补提分！`)
    healDialogVisible.value = false
    await loadFinalizeAudit()
  } catch (e) {
    ElMessage.error(e.message || '分集自愈失败')
  } finally {
    healingEp.value = false
  }
}

// 定稿并冻结版本
async function onLockAndFreeze() {
  try {
    await ElMessageBox.confirm(
      '确定定稿并冻结当前剧本版本吗？定稿后全剧分集将处于只读受保护状态，并允许下游视听工坊全面接入。',
      '定稿冻结确认',
      { confirmButtonText: '确定定稿冻结', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  locking.value = true
  try {
    const res = await scriptStudioAPI.lockDrama(dramaId.value)
    ElMessage.success('全剧剧本已成功定稿冻结！版本游标已更新。')
    finalizeAuditData.value.lock_status = 1
    if (res?.version_cursor) {
      finalizeAuditData.value.version_tag = `v${res.version_cursor}.0-final`
    }
    await loadFinalizeAudit()
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '定稿锁定失败')
  } finally {
    locking.value = false
  }
}

// 解除定稿锁定
async function onUnlockScript() {
  try {
    await ElMessageBox.confirm(
      '解除锁定后允许继续对各阶段剧本、大纲进行编辑修改，是否继续？',
      '解除定稿锁定',
      { confirmButtonText: '确定解锁', cancelButtonText: '取消', type: 'info' }
    )
  } catch {
    return
  }

  locking.value = true
  try {
    await scriptStudioAPI.unlockDrama(dramaId.value)
    ElMessage.success('已解除定稿锁定，剧本已恢复可编辑状态。')
    finalizeAuditData.value.lock_status = 0
    await loadFinalizeAudit()
    await loadDramaDetail()
  } catch (e) {
    ElMessage.error(e.message || '解除锁定失败')
  } finally {
    locking.value = false
  }
}

// 打开导出中心弹窗
function openExportDialog(type = 'all') {
  exportDialogVisible.value = true
}

// 单文件模拟下载
function downloadMockFile(file) {
  ElMessage.success(`正在准备导出并下载文件: ${file.name}`)
}

// 批量打包下载
async function handleBatchDownloadAll() {
  exporting.value = true
  try {
    const res = await scriptStudioAPI.exportScript(dramaId.value, {
      export_type: 'all',
      include_storyboards: true,
      include_qa_report: true
    })
    ElMessage.success('全剧工业化交付物资产包已打包完成，开始下载！')
    exportDialogVisible.value = false
  } catch (e) {
    ElMessage.error(e.message || '导出打包失败')
  } finally {
    exporting.value = false
  }
}

// 从阶段 5 跳转到阶段 4 对应集
function viewEpisodeInStage4(epNum) {
  healDialogVisible.value = false
  selectEpisode(epNum)
  activeTab.value = 'stage4_script'
}

function goCanvasMode() {
  router.push(`/film/${dramaId.value}/canvas`)
}

function openWorkflowDrawer() {
  showWorkflowDrawer.value = true
}

function goToCanvasSection(section) {
  router.push(`/film/${dramaId.value}?section=${section}`)
}

onMounted(() => {
  loadDramaDetail()
  loadAllDramas()
  setupEventSource()
  loadEpisodesNavigation()
  loadEpisodeDetail(currentEpisodeNumber.value || 3)
  loadFinalizeAudit()
})

onUnmounted(() => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
})
</script>

<style scoped>
/* 容器整体配色与暗色/浅色变量 */
.script-studio-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background-color: #f8fafc;
  color: #1e293b;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  overflow: hidden;
}

.script-studio-view.theme-dark {
  background-color: #0f172a;
  color: #f1f5f9;
}

/* 1. 顶部全局导航栏 */
.studio-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
  padding: 0 16px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.theme-dark .studio-header {
  background: #1e293b;
  border-bottom-color: #334155;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo-box {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.logo-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: #8b5cf6;
  color: #ffffff;
  border-radius: 6px;
  font-weight: bold;
  font-size: 16px;
}
.logo-text {
  display: flex;
  flex-direction: column;
}
.logo-main {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .logo-main {
  color: #f8fafc;
}
.logo-sub {
  font-size: 9px;
  color: #94a3b8;
  letter-spacing: 0.5px;
}

.drama-selector-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #f1f5f9;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}
.theme-dark .drama-selector-btn {
  background: #334155;
}
.folder-icon {
  color: #f59e0b;
}
.version-tag {
  background: #ede9fe;
  color: #7c3aed;
  border: none;
  font-weight: bold;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.nav-btn {
  border-radius: 6px;
  font-size: 13px;
}
.user-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: #a855f7;
  color: #fff;
  border-radius: 50%;
  font-size: 12px;
  font-weight: bold;
  cursor: pointer;
}

/* 2. 二级状态与操作栏 */
.studio-subbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.theme-dark .studio-subbar {
  background: #1e293b;
  border-bottom-color: #334155;
}

.subbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.back-btn {
  font-size: 13px;
  color: #64748b;
}
.current-ep-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .current-ep-title {
  color: #f8fafc;
}
.ep-tag {
  background: #ede9fe;
  color: #8b5cf6;
  border-radius: 4px;
}

.subbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.meta-pill {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
}
.theme-dark .meta-pill {
  background: #334155;
  color: #cbd5e1;
}
.meta-val {
  color: #0f172a;
  font-weight: 700;
}
.theme-dark .meta-val {
  color: #f8fafc;
}
.meta-sub {
  color: #94a3b8;
  font-size: 11px;
}

.action-btn-highlight {
  background: #faf5ff;
  border: 1px solid #d8b4fe;
  color: #7e22ce;
  border-radius: 6px;
  font-weight: 600;
}
.action-btn-highlight.is-active {
  background: #8b5cf6;
  color: #fff;
  border-color: #8b5cf6;
}
.action-btn-primary {
  background: #7c3aed;
  border-color: #7c3aed;
  border-radius: 6px;
  font-weight: 600;
}

/* 3. 主体工作区 */
.studio-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* 左侧主侧边栏 */
.studio-sidebar {
  width: 220px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  padding: 12px 10px;
  overflow-y: auto;
  flex-shrink: 0;
}
.theme-dark .studio-sidebar {
  background: #1e293b;
  border-right-color: #334155;
}

.nav-section-title {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  margin: 12px 0 6px 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.nav-tree-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
  margin-bottom: 2px;
  transition: all 0.2s;
}
.theme-dark .nav-tree-item {
  color: #cbd5e1;
}
.nav-tree-item:hover {
  background: #f1f5f9;
}
.theme-dark .nav-tree-item:hover {
  background: #334155;
}
.nav-tree-item.active {
  background: #ede9fe;
  color: #7c3aed;
  font-weight: 600;
}
.theme-dark .nav-tree-item.active {
  background: #4c1d95;
  color: #e9d5ff;
}

.item-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
}
.item-icon-box.purple {
  background: #8b5cf6;
  color: #fff;
}
.item-icon-box.green {
  background: #10b981;
  color: #fff;
}
.item-icon-box.gray {
  background: #e2e8f0;
  color: #64748b;
}
.item-icon-box.num {
  background: #f1f5f9;
  color: #64748b;
}
.theme-dark .item-icon-box.num {
  background: #334155;
  color: #94a3b8;
}

.item-label {
  flex: 1;
}
.item-badge {
  font-size: 11px;
  color: #10b981;
  background: #ecfdf5;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: bold;
}
.item-score-badge {
  font-size: 11px;
  color: #10b981;
  font-weight: bold;
}
.item-count-box {
  font-size: 11px;
  color: #10b981;
  background: #ecfdf5;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

/* 定稿契约 Bridge 卡片 */
.bridge-contract-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  margin: 10px 0;
}
.theme-dark .bridge-contract-card {
  background: #0f172a;
  border-color: #475569;
}
.bridge-lock-icon {
  color: #64748b;
  font-size: 16px;
}
.bridge-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}
.theme-dark .bridge-title {
  color: #e2e8f0;
}
.bridge-desc {
  font-size: 10px;
  color: #94a3b8;
}

.sidebar-bottom-actions {
  margin-top: auto;
  padding-top: 12px;
}
.btn-batch-concurrent {
  width: 100%;
  background: #7c3aed;
  border: none;
  font-weight: 600;
}

/* 右侧主面板 */
.studio-main-panel {
  flex: 1;
  padding: 16px 20px;
  overflow-y: auto;
  background: #f8fafc;
}
.theme-dark .studio-main-panel {
  background: #0b1120;
}

/* 阶段 0：生产管线指引卡片 */
.pipeline-guide-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 16px;
}
.theme-dark .pipeline-guide-card {
  background: #1e293b;
  border-color: #334155;
}

.guide-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.guide-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stage-num-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: #8b5cf6;
  color: #fff;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
}
.stage-name-text {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .stage-name-text {
  color: #f8fafc;
}
.stage-tag.cold {
  font-size: 11px;
  background: #f1f5f9;
  color: #64748b;
  padding: 2px 6px;
  border-radius: 4px;
}
.guide-stats {
  font-size: 12px;
  color: #10b981;
  background: #ecfdf5;
  padding: 4px 10px;
  border-radius: 6px;
}

/* 横向步进卡片流 */
.horizontal-steps-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  overflow-x: auto;
}
.h-step-item {
  flex: 1;
  min-width: 110px;
}
.step-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
}
.theme-dark .step-card {
  background: #0f172a;
  border-color: #334155;
}
.h-step-item.active .step-card {
  border-color: #8b5cf6;
  background: #faf5ff;
}
.h-step-item.done .step-card {
  border-color: #10b981;
  background: #f0fdf4;
}

.step-top {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}
.step-check {
  color: #10b981;
  font-weight: bold;
}
.step-num {
  color: #94a3b8;
  font-size: 12px;
}
.step-sub {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}
.h-step-arrow {
  color: #cbd5e1;
  font-size: 18px;
}

.guide-desc-text {
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
  margin: 0;
}
.theme-dark .guide-desc-text {
  color: #94a3b8;
}

/* 故事生成表单卡片 */
.story-form-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 20px;
}
.theme-dark .story-form-card {
  background: #1e293b;
  border-color: #334155;
}

.form-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.form-title-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.title-badge-purple {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: #8b5cf6;
  color: #fff;
  border-radius: 4px;
  font-size: 12px;
  font-weight: bold;
}
.title-main-text {
  font-size: 15px;
  font-weight: 700;
}
.title-sub-text {
  font-size: 12px;
  color: #94a3b8;
}
.engine-tag {
  background: #ede9fe;
  color: #7c3aed;
  border: none;
  font-weight: bold;
}

.story-textarea :deep(.el-textarea__inner) {
  border-radius: 6px;
  background: #f8fafc;
  border-color: #cbd5e1;
  font-size: 13px;
  line-height: 1.6;
}
.theme-dark .story-textarea :deep(.el-textarea__inner) {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

.form-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}
.row-label {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  width: 40px;
  flex-shrink: 0;
}
.tags-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.select-tag-pill {
  padding: 4px 14px;
  background: #f1f5f9;
  border-radius: 16px;
  font-size: 12px;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}
.theme-dark .select-tag-pill {
  background: #334155;
  color: #cbd5e1;
}
.select-tag-pill.active {
  background: #7c3aed;
  color: #ffffff;
  font-weight: 600;
}

.form-row-inline {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-top: 14px;
}
.inline-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stepper-box {
  display: flex;
  align-items: center;
  background: #f1f5f9;
  border-radius: 6px;
  overflow: hidden;
}
.theme-dark .stepper-box {
  background: #334155;
}
.step-btn {
  padding: 4px 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-weight: bold;
}
.step-val {
  padding: 0 8px;
  font-size: 13px;
  font-weight: 700;
}
.concurrency-hint {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 8px;
}

/* HITL 人工审核卡片 */
.hitl-control-panel {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 16px;
}
.theme-dark .hitl-control-panel {
  background: #064e3b;
  border-color: #047857;
}
.hitl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.hitl-title-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hitl-avatar {
  font-size: 16px;
}
.hitl-title {
  font-size: 13px;
  font-weight: 700;
  color: #14532d;
}
.theme-dark .hitl-title {
  color: #a7f3d0;
}
.hitl-sub {
  font-size: 11px;
  color: #15803d;
}
.theme-dark .hitl-sub {
  color: #6ee7b7;
}
.hitl-switch-box {
  display: flex;
  align-items: center;
  gap: 6px;
}
.switch-label {
  font-size: 12px;
  font-weight: 600;
  color: #15803d;
}

.hitl-options-row {
  display: flex;
  gap: 10px;
}
.hitl-option-card {
  flex: 1;
  background: #ffffff;
  border: 1px solid #dcfce7;
  border-radius: 6px;
  padding: 8px;
  text-align: center;
  cursor: pointer;
}
.theme-dark .hitl-option-card {
  background: #022c22;
  border-color: #065f46;
}
.hitl-option-card.active {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #fff;
}
.hitl-option-card.active .opt-title,
.hitl-option-card.active .opt-desc {
  color: #fff;
}
.opt-title {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
}
.opt-desc {
  font-size: 10px;
  color: #64748b;
  margin-top: 2px;
}

/* 底部操作 */
.form-footer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}
.theme-dark .form-footer-actions {
  border-top-color: #334155;
}
.footer-left-btns {
  display: flex;
  gap: 10px;
}
.btn-main-generate {
  background: #7c3aed;
  border: none;
  font-weight: 700;
  padding: 10px 24px;
  border-radius: 6px;
}

/* 阶段展示公共卡片 */
.stage-content-view {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 20px;
}
.theme-dark .stage-content-view {
  background: #1e293b;
  border-color: #334155;
}
.view-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 4px;
}
.view-desc {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 16px;
}

/* 角色矩阵卡片 */
.char-matrix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.char-matrix-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
}
.theme-dark .char-matrix-card {
  background: #0f172a;
  border-color: #334155;
}
.char-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.c-field {
  font-size: 12px;
  margin-bottom: 4px;
  color: #475569;
}
.theme-dark .c-field {
  color: #cbd5e1;
}

/* 大纲卡片流 */
.outline-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.episode-outline-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}
.outline-item-card {
  display: flex;
  gap: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
}
.theme-dark .outline-item-card {
  background: #0f172a;
  border-color: #334155;
}
.ep-num-tag {
  background: #ede9fe;
  color: #7c3aed;
  font-weight: 700;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  height: fit-content;
}
.ep-content-box {
  flex: 1;
}
.ep-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.ep-detail-text {
  font-size: 12px;
  color: #475569;
  margin-bottom: 2px;
}
.theme-dark .ep-detail-text {
  color: #cbd5e1;
}

/* ================= 阶段 1：创意立项与高概念 UI 样式 ================= */
.stage1-full-view {
  background: transparent;
  border: none;
  padding: 0;
}

.stage1-top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.stage1-main-title {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}
.theme-dark .stage1-main-title {
  color: #f8fafc;
}
.hitl-tag-pill {
  font-size: 12px;
  font-weight: 600;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 3px 10px;
  border-radius: 20px;
}
.theme-dark .hitl-tag-pill {
  background: #064e3b;
  color: #a7f3d0;
  border-color: #047857;
}

/* 审批通过绿色横幅卡片 */
.hitl-banner-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 12px 18px;
  margin-bottom: 16px;
}
.theme-dark .hitl-banner-card {
  background: #064e3b;
  border-color: #047857;
}
.banner-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #10b981;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: bold;
  flex-shrink: 0;
}
.banner-body {
  flex: 1;
}
.banner-title {
  font-size: 13px;
  font-weight: 700;
  color: #166534;
}
.theme-dark .banner-title {
  color: #bbf7d0;
}
.banner-desc {
  font-size: 11px;
  color: #15803d;
  margin-top: 2px;
}
.theme-dark .banner-desc {
  color: #86efac;
}
.banner-actions {
  display: flex;
  gap: 8px;
}

/* 概念模块大卡片 */
.concept-section-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
.theme-dark .concept-section-card {
  background: #1e293b;
  border-color: #334155;
}

.sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.sec-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: #0f172a;
  color: #ffffff;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 800;
}
.theme-dark .sec-badge {
  background: #6366f1;
}
.sec-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .sec-title {
  color: #f8fafc;
}
.sec-en {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 2px;
}

/* 一句话核心钩子 */
.hook-content-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 16px;
}
.theme-dark .hook-content-card {
  background: #0f172a;
  border-color: #334155;
}
.hook-quote-text {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.6;
  margin-bottom: 12px;
}
.theme-dark .hook-quote-text {
  color: #f1f5f9;
}
.edit-hook-input {
  margin-bottom: 12px;
}

.hook-ai-analysis {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: #475569;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 14px;
  line-height: 1.6;
}
.theme-dark .hook-ai-analysis {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.ai-robot-icon {
  font-size: 14px;
}

.hook-metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.metric-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  text-align: center;
}
.theme-dark .metric-card {
  background: #1e293b;
  border-color: #334155;
}
.metric-label {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 4px;
}
.theme-dark .metric-label {
  color: #94a3b8;
}
.metric-val {
  font-size: 18px;
  font-weight: 800;
}
.metric-val.green {
  color: #10b981;
}
.metric-val.orange {
  color: #f59e0b;
}

/* 四幕大纲 2x2 网格 */
.four-acts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.act-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .act-card {
  background: #0f172a;
  border-color: #334155;
}
.act-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.act-title-box {
  display: flex;
  align-items: center;
  gap: 6px;
}
.act-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.act-dot.blue { background: #3b82f6; }
.act-dot.purple { background: #8b5cf6; }
.act-dot.orange { background: #f59e0b; }
.act-dot.green { background: #10b981; }

.act-name {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}
.theme-dark .act-name {
  color: #f1f5f9;
}
.act-range {
  font-size: 11px;
  color: #94a3b8;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 1px 6px;
  border-radius: 4px;
}
.theme-dark .act-range {
  background: #1e293b;
  border-color: #334155;
}
.act-card-body {
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}
.theme-dark .act-card-body {
  color: #cbd5e1;
}

/* 核心伏笔池 */
.clue-pool-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .clue-pool-card {
  background: #0f172a;
  border-color: #334155;
}
.clue-pool-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.clue-head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #1e293b;
}
.theme-dark .clue-head-left {
  color: #f1f5f9;
}
.clue-icon {
  font-size: 14px;
}
.clue-count-sub {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 4px;
}
.clue-list-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.clue-item-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
}
.theme-dark .clue-item-row {
  background: #1e293b;
  border-color: #334155;
}
.clue-id-badge {
  font-family: monospace;
  font-weight: 700;
  color: #6366f1;
  background: #e0e7ff;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.theme-dark .clue-id-badge {
  background: #312e81;
  color: #c7d2fe;
}
.clue-name {
  font-weight: 600;
  color: #1e293b;
  flex: 1;
}
.theme-dark .clue-name {
  color: #f1f5f9;
}
.clue-recycle-text {
  color: #64748b;
  font-size: 11px;
}
.theme-dark .clue-recycle-text {
  color: #94a3b8;
}
.clue-edit-eps {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 商业与受众分析 */
.biz-audience-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}
.biz-subcard {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .biz-subcard {
  background: #0f172a;
  border-color: #334155;
}
.biz-subcard-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #1e293b;
  margin-bottom: 10px;
}
.theme-dark .biz-subcard-title {
  color: #f1f5f9;
}
.biz-sub-icon {
  font-size: 14px;
}
.biz-desc-text {
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}
.theme-dark .biz-desc-text {
  color: #cbd5e1;
}

/* 驱动力能量条 */
.drivers-energy-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.driver-bar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.driver-name {
  width: 70px;
  color: #475569;
  font-weight: 500;
  font-size: 11px;
}
.theme-dark .driver-name {
  color: #cbd5e1;
}
.driver-bar-track {
  flex: 1;
  height: 7px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}
.theme-dark .driver-bar-track {
  background: #334155;
}
.driver-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #8b5cf6, #ec4899);
  border-radius: 4px;
}
.driver-score {
  width: 24px;
  text-align: right;
  font-weight: 700;
  font-size: 11px;
  color: #6366f1;
}
.theme-dark .driver-score {
  color: #a5b4fc;
}

/* 付费卡点节点 */
.paywall-nodes-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
  margin-bottom: 12px;
}
.theme-dark .paywall-nodes-card {
  background: #0f172a;
  border-color: #334155;
}
.paywall-nodes-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #1e293b;
  margin-bottom: 10px;
}
.theme-dark .paywall-nodes-title {
  color: #f1f5f9;
}
.paywall-icon {
  font-size: 14px;
}
.paywall-sub {
  font-size: 11px;
  color: #94a3b8;
}
.paywall-chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.paywall-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 12px;
}
.theme-dark .paywall-chip {
  background: #1e293b;
  border-color: #334155;
}
.chip-ep {
  color: #7c3aed;
  font-weight: 700;
}
.theme-dark .chip-ep {
  color: #c084fc;
}
.chip-reason {
  color: #64748b;
  font-size: 11px;
}
.theme-dark .chip-reason {
  color: #94a3b8;
}
.chip-del {
  cursor: pointer;
  color: #ef4444;
  font-size: 12px;
  margin-left: 2px;
}

/* 商业定位卡片 */
.commercial-pos-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .commercial-pos-card {
  background: #0f172a;
  border-color: #334155;
}
.pos-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #1e293b;
  margin-bottom: 8px;
}
.theme-dark .pos-title-row {
  color: #f1f5f9;
}
.pos-icon {
  font-size: 14px;
}
.pos-desc-text {
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}
.theme-dark .pos-desc-text {
  color: #cbd5e1;
}

/* 情绪与节奏基调 */
.emotion-rhythm-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 12px;
}
.emotion-left-card,
.rhythm-right-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .emotion-left-card,
.theme-dark .rhythm-right-card {
  background: #0f172a;
  border-color: #334155;
}
.card-inner-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 10px;
}
.theme-dark .card-inner-title {
  color: #f1f5f9;
}

.curve-chart-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 10px;
}
.theme-dark .curve-chart-box {
  background: #1e293b;
  border-color: #334155;
}
.curve-svg {
  width: 100%;
  height: 70px;
  display: block;
}
.curve-axis-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #94a3b8;
  margin-top: 4px;
}
.curve-tags-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.curve-tag-btn {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 11px;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}
.theme-dark .curve-tag-btn {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.curve-tag-btn.active {
  background: #8b5cf6;
  border-color: #8b5cf6;
  color: #ffffff;
  font-weight: 600;
}

.rhythm-phases-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rhythm-phase-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 11px;
}
.theme-dark .rhythm-phase-item {
  background: #1e293b;
  border-color: #334155;
}
.rhythm-range-tag {
  font-weight: 700;
  color: #6366f1;
  background: #e0e7ff;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.theme-dark .rhythm-range-tag {
  background: #312e81;
  color: #c7d2fe;
}
.rhythm-phase-name {
  font-weight: 700;
  color: #1e293b;
  flex-shrink: 0;
}
.theme-dark .rhythm-phase-name {
  color: #f1f5f9;
}
.rhythm-phase-desc {
  color: #64748b;
  margin-left: auto;
  text-align: right;
}
.theme-dark .rhythm-phase-desc {
  color: #94a3b8;
}

/* ================= 阶段 2：故事圣经与世界观 UI 样式 ================= */
.stage2-full-view {
  background: transparent;
  border: none;
  padding: 0;
}
.stage-top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.stage-main-title {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}
.theme-dark .stage-main-title {
  color: #f8fafc;
}

/* 三大铁律网格 */
.iron-rules-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.iron-rule-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
}
.theme-dark .iron-rule-card {
  background: #0f172a;
  border-color: #334155;
}
.rule-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.rule-badge {
  font-family: monospace;
  font-weight: 800;
  font-size: 11px;
  color: #8b5cf6;
  background: #ede9fe;
  padding: 2px 6px;
  border-radius: 4px;
}
.theme-dark .rule-badge {
  background: #4c1d95;
  color: #ddd6fe;
}
.rule-name {
  font-size: 13px;
  color: #1e293b;
}
.theme-dark .rule-name {
  color: #f1f5f9;
}
.rule-desc {
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}
.theme-dark .rule-desc {
  color: #cbd5e1;
}

.worldview-sub-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.hierarchy-card, .core-conflict-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .hierarchy-card, .theme-dark .core-conflict-card {
  background: #0f172a;
  border-color: #334155;
}
.hierarchy-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hierarchy-item {
  font-size: 12px;
}
.layer-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.layer-name {
  color: #334155;
}
.theme-dark .layer-name {
  color: #e2e8f0;
}
.layer-pct {
  font-weight: 700;
}
.layer-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 4px;
}
.theme-dark .layer-track {
  background: #334155;
}
.layer-fill {
  height: 100%;
  border-radius: 4px;
}
.layer-desc {
  font-size: 11px;
  color: #64748b;
}
.theme-dark .layer-desc {
  color: #94a3b8;
}
.conflict-icon {
  font-size: 16px;
  margin-right: 4px;
}
.conflict-text {
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}
.theme-dark .conflict-text {
  color: #cbd5e1;
}

/* 九维角色档案 */
.char-tabs-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  overflow-x: auto;
}
.char-tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #475569;
  transition: all 0.2s;
}
.theme-dark .char-tab-btn {
  background: #0f172a;
  border-color: #334155;
  color: #94a3b8;
}
.char-tab-btn.active {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #ffffff;
  font-weight: 700;
}
.char-avatar-mini {
  font-size: 14px;
}
.char-tab-tag {
  font-size: 10px;
  opacity: 0.8;
}

.nine-dim-profile-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 16px;
}
.theme-dark .nine-dim-profile-card {
  background: #0f172a;
  border-color: #334155;
}
.profile-header-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 14px;
}
.theme-dark .profile-header-box {
  border-bottom-color: #334155;
}
.profile-avatar-emoji {
  font-size: 32px;
}
.profile-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.profile-name {
  font-size: 15px;
  color: #0f172a;
}
.theme-dark .profile-name {
  color: #f8fafc;
}
.profile-seed {
  font-family: monospace;
  font-size: 10px;
  color: #94a3b8;
}
.profile-summary-text {
  font-size: 12px;
  color: #475569;
}
.theme-dark .profile-summary-text {
  color: #cbd5e1;
}

.nine-dim-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.dim-col-span-2 {
  grid-column: span 2;
}
.dim-field-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
}
.theme-dark .dim-field-card {
  background: #1e293b;
  border-color: #334155;
}
.dim-label {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 4px;
}
.theme-dark .dim-label {
  color: #94a3b8;
}
.dim-val {
  font-size: 12px;
  color: #1e293b;
  line-height: 1.4;
}
.theme-dark .dim-val {
  color: #f1f5f9;
}
.highlight-green {
  color: #059669;
  font-weight: 600;
}
.highlight-orange {
  color: #d97706;
  font-weight: 600;
}
.highlight-purple {
  color: #7c3aed;
  font-weight: 600;
}

/* 关系网络动态图 */
.relation-timeline-box {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  background: #f8fafc;
  padding: 8px 12px;
  border-radius: 6px;
}
.theme-dark .relation-timeline-box {
  background: #0f172a;
}
.timeline-hint {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}
.timeline-nodes-row {
  display: flex;
  gap: 6px;
}
.timeline-ep-btn {
  padding: 4px 10px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}
.theme-dark .timeline-ep-btn {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}
.timeline-ep-btn.active {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #ffffff;
}

.relation-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}
.relation-item-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}
.theme-dark .relation-item-card {
  background: #0f172a;
  border-color: #334155;
}
.rel-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  font-size: 12px;
  margin-bottom: 6px;
}
.rel-entity.from {
  color: #7c3aed;
}
.rel-arrow {
  color: #94a3b8;
}
.rel-entity.to {
  color: #2563eb;
}
.rel-tag-pill {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  color: #059669;
  background: #ecfdf5;
  padding: 1px 6px;
  border-radius: 4px;
  margin-bottom: 6px;
}
.theme-dark .rel-tag-pill {
  background: #064e3b;
  color: #a7f3d0;
}
.rel-desc-text {
  font-size: 11px;
  color: #64748b;
}
.theme-dark .rel-desc-text {
  color: #94a3b8;
}

/* 核心道具卡片 */
.props-list-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.prop-item-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}
.theme-dark .prop-item-card {
  background: #0f172a;
  border-color: #334155;
}
.prop-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.prop-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.prop-name {
  font-size: 13px;
  color: #0f172a;
}
.theme-dark .prop-name {
  color: #f8fafc;
}
.prop-id {
  font-family: monospace;
  font-size: 10px;
  color: #94a3b8;
}
.prop-desc {
  font-size: 12px;
  color: #475569;
  margin-bottom: 10px;
}
.theme-dark .prop-desc {
  color: #cbd5e1;
}
.prop-fragments-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
}
.theme-dark .prop-fragments-box {
  background: #1e293b;
  border-color: #334155;
}
.frag-title {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 4px;
}
.frag-item {
  font-size: 11px;
  color: #334155;
  margin-bottom: 4px;
  line-height: 1.4;
}
.theme-dark .frag-item {
  color: #cbd5e1;
}
.frag-ep {
  font-weight: 700;
  color: #7c3aed;
  margin-right: 4px;
}
.prop-prompt-box {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 4px;
  padding: 8px;
}
.theme-dark .prop-prompt-box {
  background: #1e3a8a;
  border-color: #1d4ed8;
}
.prompt-title {
  font-size: 11px;
  font-weight: 700;
  color: #1d4ed8;
  margin-bottom: 4px;
}
.theme-dark .prompt-title {
  color: #93c5fd;
}
.prompt-content {
  font-size: 11px;
  color: #1e40af;
  line-height: 1.4;
}
.theme-dark .prompt-content {
  color: #bfdbfe;
}

/* 声音配乐设计 */
.music-overall-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
}
.theme-dark .music-overall-box {
  background: #0f172a;
  border-color: #334155;
}
.music-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.music-bpm-badge {
  font-size: 11px;
  color: #7c3aed;
  background: #ede9fe;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.theme-dark .music-bpm-badge {
  background: #4c1d95;
  color: #ddd6fe;
}
.music-style-text {
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}
.theme-dark .music-style-text {
  color: #cbd5e1;
}

.motifs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}
.motif-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
}
.theme-dark .motif-card {
  background: #0f172a;
  border-color: #334155;
}
.motif-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.motif-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.motif-name {
  font-size: 12px;
  color: #1e293b;
  flex: 1;
}
.theme-dark .motif-name {
  color: #f1f5f9;
}
.motif-bpm {
  font-size: 10px;
  color: #64748b;
  font-weight: 600;
}
.motif-field {
  font-size: 11px;
  color: #475569;
  margin-bottom: 4px;
}
.theme-dark .motif-field {
  color: #cbd5e1;
}

/* ================= 阶段 3：三级大纲 UI 样式 (含 Sticky Top 与 Sticky Bottom) ================= */
.stage3-full-container {
  display: flex;
  flex-direction: column;
  position: relative;
  background: transparent;
  border: none;
  padding: 0;
}

/* 顶部常驻一级总纲概览 (Sticky Top) */
.stage3-sticky-top-header {
  position: sticky;
  top: -16px;
  z-index: 20;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 18px;
  margin-bottom: 14px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.theme-dark .stage3-sticky-top-header {
  background: #1e293b;
  border-color: #334155;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
.stage3-top-summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.stage3-top-left {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.s3-badge-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.s3-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: #7c3aed;
  color: #fff;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
}
.s3-title-text {
  font-size: 14px;
  color: #0f172a;
}
.theme-dark .s3-title-text {
  color: #f8fafc;
}
.s3-sub-hook {
  font-size: 12px;
  color: #7c3aed;
  font-weight: 600;
}
.s3-four-acts-summary {
  display: flex;
  gap: 8px;
}
.act-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.act-chip.blue { background: #dbeafe; color: #1e40af; }
.act-chip.purple { background: #ede9fe; color: #6d28d9; }
.act-chip.orange { background: #ffedd5; color: #c2410c; }
.act-chip.green { background: #dcfce7; color: #15803d; }
.theme-dark .act-chip.blue { background: #1e3a8a; color: #93c5fd; }
.theme-dark .act-chip.purple { background: #4c1d95; color: #ddd6fe; }
.theme-dark .act-chip.orange { background: #7c2d12; color: #fdba74; }
.theme-dark .act-chip.green { background: #064e3b; color: #86efac; }
.btn-jump-stage1 {
  color: #7c3aed;
  border-color: #c4b5fd;
}

/* 中部滚动区 */
.stage3-scrollable-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 二级四幕卡片网格 */
.two-level-acts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.act-breakdown-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
}
.theme-dark .act-breakdown-card {
  background: #0f172a;
  border-color: #334155;
}
.act-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.act-name-box {
  display: flex;
  align-items: center;
  gap: 6px;
}
.act-num-pill {
  font-size: 10px;
  font-weight: 700;
  color: #7c3aed;
  background: #ede9fe;
  padding: 2px 6px;
  border-radius: 4px;
}
.theme-dark .act-num-pill {
  background: #4c1d95;
  color: #ddd6fe;
}
.act-title {
  font-size: 13px;
  color: #0f172a;
}
.theme-dark .act-title {
  color: #f8fafc;
}
.act-ep-range {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}
.act-field-item {
  margin-bottom: 6px;
  font-size: 11px;
}
.f-label {
  color: #64748b;
  font-weight: 600;
  margin-bottom: 2px;
}
.f-val {
  color: #334155;
  line-height: 1.4;
}
.theme-dark .f-val {
  color: #cbd5e1;
}
.highlight-blue {
  color: #2563eb;
  font-weight: 600;
}
.theme-dark .highlight-blue {
  color: #60a5fa;
}
.act-bottom-emotion {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: #94a3b8;
  padding-top: 6px;
  border-top: 1px dashed #e2e8f0;
  margin-top: 6px;
}
.theme-dark .act-bottom-emotion {
  border-top-color: #334155;
}
.emo-score {
  color: #e11d48;
  font-weight: 700;
}

/* 分集节拍表格 */
.beats-table-wrapper {
  overflow-x: auto;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
}
.theme-dark .beats-table-wrapper {
  background: #1e293b;
  border-color: #334155;
}
.beats-data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.beats-data-table th, .beats-data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}
.theme-dark .beats-data-table th, .theme-dark .beats-data-table td {
  border-bottom-color: #334155;
}
.beats-data-table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 700;
}
.theme-dark .beats-data-table th {
  background: #0f172a;
  color: #94a3b8;
}
.td-ep-num {
  font-family: monospace;
  font-weight: 800;
  color: #7c3aed;
}
.scene-tag {
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.theme-dark .scene-tag {
  background: #1e3a8a;
  color: #93c5fd;
}
.reversal-text {
  color: #d97706;
  font-weight: 600;
}
.cliffhanger-highlight {
  color: #e11d48;
  font-weight: 700;
}
.status-done-text {
  color: #059669;
  font-weight: 600;
  font-size: 11px;
}

/* 主场景库占比 */
.scenes-pool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.scene-pool-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}
.theme-dark .scene-pool-card {
  background: #0f172a;
  border-color: #334155;
}
.sc-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 12px;
}
.sc-name {
  color: #1e293b;
}
.theme-dark .sc-name {
  color: #f1f5f9;
}
.sc-pct {
  font-weight: 700;
  color: #7c3aed;
}
.sc-bar-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}
.theme-dark .sc-bar-track {
  background: #334155;
}
.sc-bar-fill {
  height: 100%;
  background: #7c3aed;
  border-radius: 4px;
}
.sc-desc {
  font-size: 11px;
  color: #64748b;
}
.theme-dark .sc-desc {
  color: #94a3b8;
}

/* 底部常驻固定区：HITL 人工干预控制栏 (Sticky Bottom) */
.stage3-sticky-bottom-bar {
  position: sticky;
  bottom: -16px;
  z-index: 30;
  background: #064e3b;
  border: 1px solid #047857;
  border-radius: 8px;
  padding: 12px 20px;
  margin-top: 14px;
  box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.25);
  color: #ecfdf5;
}
.hitl-bottom-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.hitl-chips-box {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.hitl-bar-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #a7f3d0;
}
.hitl-ok-icon {
  font-size: 16px;
  color: #34d399;
}
.hitl-metric-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.metric-chip-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #022c22;
  border: 1px solid #059669;
  border-radius: 20px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #a7f3d0;
}
.chk-icon {
  color: #34d399;
}
.chk-val {
  color: #6ee7b7;
  font-weight: 700;
}

.hitl-actions-box {
  display: flex;
  align-items: center;
  gap: 8px;
}
.btn-hitl-edit, .btn-hitl-regen, .btn-hitl-val {
  background: #022c22;
  border-color: #059669;
  color: #ecfdf5;
}
.btn-hitl-edit:hover, .btn-hitl-regen:hover, .btn-hitl-val:hover {
  background: #047857;
  color: #ffffff;
}
.btn-hitl-confirm {
  font-weight: 700;
}

/* ================= 阶段 4：故事剧本三栏工坊 UI 高保真样式 ================= */
.stage4-full-workbench {
  padding: 0 !important;
  background: transparent !important;
  border: none !important;
  height: calc(100vh - 122px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.stage4-studio-layout {
  display: flex;
  flex-direction: row;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: #f8fafc;
}
.theme-dark .stage4-studio-layout {
  background: #0b1120;
}

/* 1. 左侧：集数导航 */
.stage4-episodes-nav-col {
  width: 270px;
  min-width: 250px;
  max-width: 290px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.theme-dark .stage4-episodes-nav-col {
  background: #1e293b;
  border-right-color: #334155;
}

.ep-nav-top-header {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.theme-dark .ep-nav-top-header {
  border-bottom-color: #334155;
}
.ep-nav-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.ep-nav-title-text {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .ep-nav-title-text {
  color: #f8fafc;
}
.ep-nav-total-badge {
  font-size: 11px;
  background: #ede9fe;
  color: #7c3aed;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 12px;
}
.theme-dark .ep-nav-total-badge {
  background: #4c1d95;
  color: #ddd6fe;
}
.ep-nav-search-wrap {
  width: 100%;
}
.ep-search-input :deep(.el-input__wrapper) {
  background: #f8fafc;
  border-radius: 6px;
  box-shadow: none;
  border: 1px solid #e2e8f0;
}
.theme-dark .ep-search-input :deep(.el-input__wrapper) {
  background: #0f172a;
  border-color: #334155;
}

/* 导航列表区域滚动 */
.ep-nav-scroll-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 8px;
}
.ep-unit-group-block {
  margin-bottom: 12px;
}
.ep-unit-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  padding: 4px 6px;
  margin-bottom: 4px;
}
.theme-dark .ep-unit-header-row {
  color: #94a3b8;
}
.unit-paywall-tag {
  font-size: 10px;
  color: #8b5cf6;
  background: #f3e8ff;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.theme-dark .unit-paywall-tag {
  background: #3b0764;
  color: #d8b4fe;
}

.ep-unit-items-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

/* 单集条目与 Hover 平移伸缩动效 */
.ep-list-item-row {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
  overflow: hidden;
}
.ep-list-item-row:hover {
  background: #f1f5f9;
}
.theme-dark .ep-list-item-row:hover {
  background: #334155;
}
.ep-list-item-row.active {
  background: #ede9fe;
  border-left: 3px solid #7c3aed;
}
.theme-dark .ep-list-item-row.active {
  background: #2e1065;
  border-left: 3px solid #a855f7;
}

.ep-item-left-info {
  display: flex;
  align-items: center;
  gap: 7px;
  overflow: hidden;
  flex: 1;
}
.ep-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ep-status-dot.dot-green {
  background: #10b981;
}
.ep-status-dot.dot-orange {
  background: #f59e0b;
}
.ep-status-dot.dot-gray {
  background: #cbd5e1;
}
.theme-dark .ep-status-dot.dot-gray {
  background: #475569;
}
.ep-number-text {
  font-family: monospace;
  font-size: 11px;
  font-weight: 700;
  color: #7c3aed;
  flex-shrink: 0;
}
.theme-dark .ep-number-text {
  color: #c084fc;
}
.ep-title-text {
  font-size: 12px;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.theme-dark .ep-title-text {
  color: #e2e8f0;
}
.ep-list-item-row.active .ep-title-text {
  font-weight: 700;
  color: #6d28d9;
}
.theme-dark .ep-list-item-row.active .ep-title-text {
  color: #ddd6fe;
}

/* 右侧徽章与平移悬浮按钮组 */
.ep-item-right-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  width: 64px;
  flex-shrink: 0;
}
.ep-normal-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s;
  will-change: transform;
}
.ep-score-value {
  font-family: monospace;
  font-size: 11px;
  font-weight: 700;
  color: #10b981;
}
.ep-score-empty {
  font-family: monospace;
  font-size: 11px;
  color: #94a3b8;
}
.ep-badge-pill {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 600;
}
.ep-badge-pill.badge-concurrent {
  background: #dbeafe;
  color: #2563eb;
}
.theme-dark .ep-badge-pill.badge-concurrent {
  background: #1e3a8a;
  color: #93c5fd;
}
.ep-badge-pill.badge-stale {
  background: #fee2e2;
  color: #ef4444;
}

/* Hover 时触发：徽章左移，操作按钮浮现 */
.ep-hover-actions-group {
  position: absolute;
  right: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  opacity: 0;
  transform: translateX(10px);
  pointer-events: none;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.ep-circle-act-btn {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  padding: 0;
}
.ep-circle-act-btn:hover {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #ffffff;
}
.theme-dark .ep-circle-act-btn {
  background: #1e293b;
  border-color: #475569;
  color: #cbd5e1;
}
.theme-dark .ep-circle-act-btn:hover {
  background: #8b5cf6;
  border-color: #8b5cf6;
  color: #ffffff;
}

.ep-list-item-row:hover .ep-normal-badges {
  transform: translateX(-54px);
}
.ep-list-item-row:hover .ep-hover-actions-group {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}

.ep-nav-empty {
  font-size: 12px;
  color: #94a3b8;
  text-align: center;
  padding: 20px 0;
}

.ep-nav-bottom-actions {
  padding: 10px 12px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #fafafa;
  flex-shrink: 0;
}
.theme-dark .ep-nav-bottom-actions {
  background: #0f172a;
  border-top-color: #334155;
}
.btn-batch-generate-range {
  width: 100%;
  background: #7c3aed;
  border-color: #7c3aed;
  font-weight: 600;
  font-size: 12px;
}
.btn-batch-generate-next,
.btn-add-single-ep {
  width: 100%;
  font-size: 11px;
}

/* 2. 中部：AST 四分块剧本工作台 */
.stage4-center-main-col {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 14px 18px;
  background: #f8fafc;
}
.theme-dark .stage4-center-main-col {
  background: #0b1120;
}

.center-top-header-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.theme-dark .center-top-header-card {
  background: #1e293b;
  border-color: #334155;
}
.current-ep-main-title {
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 8px 0;
}
.theme-dark .current-ep-main-title {
  color: #f8fafc;
}
.center-meta-pills-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.meta-pill-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.meta-pill-tag.purple {
  background: #ede9fe;
  color: #7c3aed;
}
.theme-dark .meta-pill-tag.purple {
  background: #4c1d95;
  color: #ddd6fe;
}
.meta-pill-tag.green {
  background: #dcfce7;
  color: #15803d;
}
.theme-dark .meta-pill-tag.green {
  background: #064e3b;
  color: #86efac;
}
.meta-pill-tag.dark-gray {
  background: #f1f5f9;
  color: #475569;
}
.theme-dark .meta-pill-tag.dark-gray {
  background: #334155;
  color: #cbd5e1;
}
.meta-pill-tag.purple-light {
  background: #fae8ff;
  color: #a21caf;
}
.theme-dark .meta-pill-tag.purple-light {
  background: #581c87;
  color: #f0abfc;
}

/* AST 四分块容器与卡片 */
.ast-blocks-display-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}
.ast-card-block {
  position: relative;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  transition: border-color 0.2s;
}
.theme-dark .ast-card-block {
  background: #1e293b;
  border-color: #334155;
}
.ast-card-block:hover {
  border-color: #cbd5e1;
}
.ast-card-block.with-patch-badge {
  border-left: 3px solid #8b5cf6;
}
.patch-badge-corner {
  position: absolute;
  top: 10px;
  right: 14px;
  font-size: 10px;
  font-weight: 700;
  color: #7c3aed;
  background: #ede9fe;
  padding: 2px 8px;
  border-radius: 12px;
}
.theme-dark .patch-badge-corner {
  background: #4c1d95;
  color: #ddd6fe;
}
.ast-block-header-label {
  font-size: 13px;
  font-weight: 800;
  color: #1e293b;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
}
.theme-dark .ast-block-header-label {
  color: #f1f5f9;
}
.ast-block-body-shots {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ast-shot-item-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}
.theme-dark .ast-shot-item-row {
  color: #cbd5e1;
}
.shot-triangle {
  color: #8b5cf6;
  font-size: 9px;
  margin-top: 4px;
}
.shot-type-title {
  color: #0f172a;
  font-weight: 700;
  flex-shrink: 0;
}
.theme-dark .shot-type-title {
  color: #f8fafc;
}
.shot-type-title.amber-highlight {
  color: #d97706;
}
.shot-text-content :deep(.highlight-action) {
  color: #7c3aed;
  font-weight: 700;
  background: #f5f3ff;
  padding: 0 4px;
  border-radius: 2px;
}
.theme-dark .shot-text-content :deep(.highlight-action) {
  color: #c084fc;
  background: #2e1065;
}

/* 块 3 对白 */
.ast-dialogue-grid-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.dialogue-item-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  font-size: 13px;
  line-height: 1.6;
}
.dia-role-column {
  display: flex;
  align-items: baseline;
  gap: 4px;
  width: 140px;
  flex-shrink: 0;
}
.dia-role-text {
  font-weight: 700;
  color: #7c3aed;
}
.theme-dark .dia-role-text {
  color: #c084fc;
}
.dia-action-text {
  font-size: 11px;
  color: #94a3b8;
}
.dia-speech-column {
  flex: 1;
  color: #1e293b;
}
.theme-dark .dia-speech-column {
  color: #e2e8f0;
}

/* 底部指标状态栏 */
.stage4-status-bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 16px;
  margin-top: 14px;
  flex-shrink: 0;
}
.theme-dark .stage4-status-bottom-bar {
  background: #1e293b;
  border-color: #334155;
}
.status-metric-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.metric-lbl {
  color: #64748b;
}
.metric-val {
  color: #0f172a;
  font-family: monospace;
  font-weight: 700;
}
.theme-dark .metric-val {
  color: #f8fafc;
}
.metric-val.green-text {
  color: #10b981;
}
.metric-val.purple-text {
  color: #8b5cf6;
}
.sse-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sse-pulse-circle {
  width: 7px;
  height: 7px;
  background: #10b981;
  border-radius: 50%;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.3);
  animation: sse-pulse 2s infinite;
}
@keyframes sse-pulse {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
.sse-label {
  color: #10b981;
  font-size: 11px;
  font-weight: 600;
}

/* 3. 右侧：质检与连续性侧边栏 */
.stage4-quality-sidebar-col {
  width: 330px;
  min-width: 300px;
  max-width: 360px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.theme-dark .stage4-quality-sidebar-col {
  background: #1e293b;
  border-left-color: #334155;
}
.qa-side-top-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.theme-dark .qa-side-top-header {
  border-bottom-color: #334155;
}
.qa-side-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .qa-side-title {
  color: #f8fafc;
}
.qa-realtime-pill {
  font-size: 10px;
  font-weight: 700;
  color: #10b981;
  background: #dcfce7;
  padding: 1px 6px;
  border-radius: 10px;
}
.theme-dark .qa-realtime-pill {
  background: #064e3b;
  color: #6ee7b7;
}

.qa-side-scrollable-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.qa-score-main-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px;
  text-align: center;
}
.theme-dark .qa-score-main-card {
  background: #0f172a;
  border-color: #334155;
}
.qa-score-big-number {
  font-size: 36px;
  font-weight: 900;
  color: #7c3aed;
  line-height: 1;
  margin-bottom: 4px;
  font-family: monospace;
}
.theme-dark .qa-score-big-number {
  color: #a855f7;
}
.qa-score-desc-title {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}
.qa-score-pass-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  color: #10b981;
  background: #dcfce7;
  padding: 2px 8px;
  border-radius: 12px;
  margin-bottom: 12px;
}
.theme-dark .qa-score-pass-badge {
  background: #064e3b;
  color: #6ee7b7;
}

.qa-radar-svg-wrapper {
  position: relative;
  width: 100%;
  margin-top: 6px;
}
.radar-svg {
  width: 100%;
  height: 140px;
  display: block;
}
.radar-metrics-labels-grid {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 10px;
  color: #64748b;
  margin-top: 8px;
}
.radar-lbl .val.green {
  color: #10b981;
  font-weight: 700;
}
.radar-lbl .val.orange {
  color: #f59e0b;
  font-weight: 700;
}

.qa-section-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
}
.theme-dark .qa-section-card {
  background: #0f172a;
  border-color: #334155;
}
.qa-card-header-title {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.theme-dark .qa-card-header-title {
  color: #f1f5f9;
}
.qa-patches-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.qa-patch-item-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 11px;
}
.theme-dark .qa-patch-item-box {
  background: #1e293b;
  border-color: #334155;
}
.patch-box-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.patch-tag-pill {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
}
.patch-tag-pill.dialogue {
  background: #ede9fe;
  color: #7c3aed;
}
.theme-dark .patch-tag-pill.dialogue {
  background: #4c1d95;
  color: #ddd6fe;
}
.patch-tag-pill.cliffhanger {
  background: #fef3c7;
  color: #d97706;
}
.theme-dark .patch-tag-pill.cliffhanger {
  background: #78350f;
  color: #fde68a;
}
.patch-box-title {
  font-size: 11px;
  color: #0f172a;
}
.theme-dark .patch-box-title {
  color: #f8fafc;
}
.patch-box-desc {
  color: #64748b;
  line-height: 1.4;
}
.theme-dark .patch-box-desc {
  color: #94a3b8;
}

.qa-info-gaps-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.info-gap-item-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 11px;
}
.theme-dark .info-gap-item-box {
  background: #1e293b;
  border-color: #334155;
}
.gap-char-header {
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
}
.theme-dark .gap-char-header {
  color: #f8fafc;
}
.gap-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 3px;
  line-height: 1.4;
}
.gap-badge-label {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 3px;
  flex-shrink: 0;
}
.gap-badge-label.known {
  background: #dcfce7;
  color: #15803d;
}
.theme-dark .gap-badge-label.known {
  background: #064e3b;
  color: #86efac;
}
.gap-badge-label.unknown {
  background: #fee2e2;
  color: #b91c1c;
}
.theme-dark .gap-badge-label.unknown {
  background: #7f1d1d;
  color: #fca5a5;
}
.gap-text-detail {
  color: #475569;
  font-size: 10.5px;
}
.theme-dark .gap-text-detail {
  color: #cbd5e1;
}

/* ========================================================================= */
/* 阶段 5：复盘定稿与全剧归宿校验 (高保真全屏看板 + 底部固定核心操作交互栏) */
/* ========================================================================= */
.stage5-full-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 120px; /* 给底部固定交互栏预留空间 */
}

.stage5-header-title-bar {
  margin-bottom: 4px;
}
.stage-main-title {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .stage-main-title {
  color: #f8fafc;
}

/* 1. 顶部总览卡片 */
.stage5-top-summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.theme-dark .stage5-top-summary-card {
  background: #1e293b;
  border-color: #334155;
}
.top-sum-left {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sum-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.sum-drama-name {
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}
.theme-dark .sum-drama-name {
  color: #f8fafc;
}
.sum-tag-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.sum-tag-pill.purple {
  background: #ede9fe;
  color: #7c3aed;
}
.theme-dark .sum-tag-pill.purple {
  background: #4c1d95;
  color: #ddd6fe;
}
.sum-tag-pill.status.locked {
  background: #dcfce7;
  color: #15803d;
}
.theme-dark .sum-tag-pill.status.locked {
  background: #064e3b;
  color: #86efac;
}
.sum-tag-pill.status.pending {
  background: #fef3c7;
  color: #b45309;
}
.theme-dark .sum-tag-pill.status.pending {
  background: #78350f;
  color: #fde68a;
}
.sum-desc-text {
  font-size: 12px;
  color: #64748b;
}
.theme-dark .sum-desc-text {
  color: #94a3b8;
}

.top-sum-metrics-grid {
  display: flex;
  align-items: center;
  gap: 16px;
}
.sum-metric-box {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.sum-metric-box .m-lbl {
  font-size: 10px;
  color: #94a3b8;
}
.sum-metric-box .m-val {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
  font-family: monospace;
}
.theme-dark .sum-metric-box .m-val {
  color: #f8fafc;
}
.sum-metric-box .m-val.green {
  color: #10b981;
}
.sum-metric-box .m-val.purple {
  color: #7c3aed;
}
.theme-dark .sum-metric-box .m-val.purple {
  color: #c084fc;
}
.lock-status-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 4px;
}
.lock-status-tag.is-locked {
  background: #dcfce7;
  color: #15803d;
}
.theme-dark .lock-status-tag.is-locked {
  background: #064e3b;
  color: #86efac;
}
.lock-status-tag.is-unlocked {
  background: #f1f5f9;
  color: #64748b;
}
.theme-dark .lock-status-tag.is-unlocked {
  background: #334155;
  color: #cbd5e1;
}

/* 阶段 5 模块卡片通用容器 */
.stage5-section-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}
.theme-dark .stage5-section-card {
  background: #1e293b;
  border-color: #334155;
}

.section-badge-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-badge-header.between {
  justify-content: space-between;
}
.header-left-part {
  display: flex;
  align-items: center;
  gap: 8px;
}
.badge-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: #7c3aed;
  color: #ffffff;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 800;
}
.badge-title {
  font-size: 14px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .badge-title {
  color: #f8fafc;
}
.badge-subtitle {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
}

/* 2. 五阶质检雷达大屏双列 */
.radar-analytics-two-col {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 20px;
}
.radar-left-panel {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.theme-dark .radar-left-panel {
  background: #0f172a;
  border-color: #334155;
}
.overall-health-score-num {
  font-size: 42px;
  font-weight: 900;
  color: #7c3aed;
  line-height: 1;
  font-family: monospace;
  margin-bottom: 4px;
}
.theme-dark .overall-health-score-num {
  color: #c084fc;
}
.overall-score-lbl {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}
.theme-dark .overall-score-lbl {
  color: #f1f5f9;
}
.overall-weights-desc {
  font-size: 10.5px;
  color: #94a3b8;
  line-height: 1.4;
  margin-bottom: 8px;
}
.low-score-warn-badge {
  font-size: 11px;
  color: #b45309;
  background: #fef3c7;
  padding: 3px 10px;
  border-radius: 12px;
  margin-bottom: 12px;
}
.theme-dark .low-score-warn-badge {
  background: #78350f;
  color: #fde68a;
}
.warn-count {
  font-weight: 800;
  color: #b91c1c;
}
.theme-dark .warn-count {
  color: #f87171;
}

.global-radar-svg-box {
  position: relative;
  width: 280px;
  height: 240px;
}
.global-radar-svg {
  width: 100%;
  height: 100%;
}
.radar-node-label {
  position: absolute;
  font-size: 10px;
  color: #475569;
  white-space: nowrap;
}
.theme-dark .radar-node-label {
  color: #cbd5e1;
}
.radar-node-label .val {
  font-weight: 800;
  color: #7c3aed;
}
.theme-dark .radar-node-label .val {
  color: #c084fc;
}
.radar-node-label.top { top: 2px; left: 50%; transform: translateX(-50%); }
.radar-node-label.right-top { top: 60px; right: -10px; }
.radar-node-label.right-bottom { bottom: 12px; right: 10px; }
.radar-node-label.left-bottom { bottom: 12px; left: 10px; }
.radar-node-label.left-top { top: 60px; left: -10px; }

.radar-right-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.qa-dim-bars-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
}
.theme-dark .qa-dim-bars-list {
  background: #0f172a;
  border-color: #334155;
}
.qa-dim-bar-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.dim-bar-lbl {
  width: 70px;
  font-weight: 700;
  color: #334155;
}
.theme-dark .dim-bar-lbl {
  color: #cbd5e1;
}
.dim-bar-track {
  flex: 1;
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}
.theme-dark .dim-bar-track {
  background: #334155;
}
.dim-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}
.dim-bar-score {
  width: 70px;
  text-align: right;
  font-family: monospace;
}
.sc-curr {
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .sc-curr {
  color: #f8fafc;
}
.sc-max {
  font-size: 10px;
  color: #94a3b8;
}

/* AST 自愈统计 */
.ast-heal-analytics-box {
  background: #faf5ff;
  border: 1px solid #e9d5ff;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.theme-dark .ast-heal-analytics-box {
  background: #2e1065;
  border-color: #581c87;
}
.heal-box-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.heal-head-title {
  font-size: 13px;
  font-weight: 800;
  color: #581c87;
}
.theme-dark .heal-head-title {
  color: #e9d5ff;
}
.heal-head-sub {
  font-size: 10.5px;
  color: #7e22ce;
}
.theme-dark .heal-head-sub {
  color: #c084fc;
}

.heal-stats-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.heal-stat-card {
  background: #ffffff;
  border: 1px solid #f3e8ff;
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.theme-dark .heal-stat-card {
  background: #1e1b4b;
  border-color: #4338ca;
}
.st-lbl {
  font-size: 10px;
  color: #6b7280;
}
.st-val {
  font-size: 14px;
  font-weight: 800;
  font-family: monospace;
  color: #0f172a;
}
.theme-dark .st-val {
  color: #f8fafc;
}
.st-val.purple { color: #7c3aed; }
.st-val.green { color: #10b981; }
.heal-bottom-desc {
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
}
.theme-dark .heal-bottom-desc {
  color: #cbd5e1;
}

/* 3. 交付矩阵与导出中心 */
.delivery-matrix-filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.matrix-stats-pills {
  display: flex;
  gap: 8px;
}
.matrix-pill {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
}
.matrix-pill.purple { background: #ede9fe; color: #6d28d9; }
.matrix-pill.green { background: #dcfce7; color: #15803d; }
.matrix-pill.orange { background: #ffedd5; color: #c2410c; }
.theme-dark .matrix-pill.purple { background: #4c1d95; color: #ddd6fe; }
.theme-dark .matrix-pill.green { background: #064e3b; color: #86efac; }
.theme-dark .matrix-pill.orange { background: #7c2d12; color: #fdba74; }

.matrix-filter-tabs {
  display: flex;
  gap: 4px;
}
.matrix-tab-btn {
  font-size: 11px;
  padding: 4px 10px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #64748b;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}
.theme-dark .matrix-tab-btn {
  background: #1e293b;
  border-color: #334155;
  color: #94a3b8;
}
.matrix-tab-btn.active {
  background: #7c3aed;
  color: #ffffff;
  border-color: #7c3aed;
  font-weight: 700;
}

.episodes-delivery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(68px, 1fr));
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
  padding: 4px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.theme-dark .episodes-delivery-grid {
  background: #0f172a;
  border-color: #334155;
}
.matrix-ep-card {
  position: relative;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s;
  user-select: none;
}
.theme-dark .matrix-ep-card {
  background: #1e293b;
  border-color: #334155;
}
.matrix-ep-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  border-color: #7c3aed;
}
.matrix-ep-card.is-active {
  border-color: #7c3aed;
  background: #ede9fe;
}
.theme-dark .matrix-ep-card.is-active {
  background: #3b0764;
  border-color: #a855f7;
}
.matrix-ep-card.is-low-score {
  border-color: #f87171;
  background: #fff1f2;
}
.theme-dark .matrix-ep-card.is-low-score {
  background: #4c0519;
  border-color: #e11d48;
}
.ep-paywall-dot {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #e11d48;
}
.ep-card-top-num {
  font-family: monospace;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
}
.theme-dark .ep-card-top-num {
  color: #94a3b8;
}
.ep-card-score {
  font-family: monospace;
  font-size: 12px;
  font-weight: 800;
  margin: 1px 0;
}
.ep-card-score.green { color: #10b981; }
.ep-card-score.orange { color: #f59e0b; }
.ep-card-score.red { color: #e11d48; }
.ep-card-title-text {
  font-size: 9px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.theme-dark .ep-card-title-text {
  color: #cbd5e1;
}

.export-center-action-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.export-act-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.theme-dark .export-act-card {
  background: #0f172a;
  border-color: #334155;
}
.export-act-card:hover {
  background: #f1f5f9;
  border-color: #7c3aed;
}
.theme-dark .export-act-card:hover {
  background: #1e293b;
}
.export-card-icon {
  font-size: 22px;
}
.export-card-title {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .export-card-title {
  color: #f8fafc;
}
.export-card-sub {
  font-size: 11px;
  color: #64748b;
}
.theme-dark .export-card-sub {
  color: #94a3b8;
}

/* 4. 角色弧光与伏笔回收看板 */
.char-arc-cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.char-arc-audit-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.theme-dark .char-arc-audit-card {
  background: #0f172a;
  border-color: #334155;
}
.char-arc-head-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.char-avatar-mini-box {
  width: 28px;
  height: 28px;
  background: #ede9fe;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}
.theme-dark .char-avatar-mini-box {
  background: #4c1d95;
}
.char-name-col {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.c-name {
  font-size: 13px;
  color: #0f172a;
}
.theme-dark .c-name {
  color: #f8fafc;
}
.c-status {
  font-size: 10.5px;
  color: #10b981;
  font-family: monospace;
}

.char-arc-state-shift-box {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}
.state-pill {
  padding: 2px 8px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #334155;
}
.theme-dark .state-pill {
  background: #334155;
  color: #cbd5e1;
}
.state-pill.init { background: #fee2e2; color: #991b1b; }
.state-pill.end { background: #dcfce7; color: #166534; }
.theme-dark .state-pill.init { background: #7f1d1d; color: #fca5a5; }
.theme-dark .state-pill.end { background: #064e3b; color: #86efac; }
.state-arrow {
  color: #94a3b8;
  font-weight: 700;
}

.char-arc-timeline-list {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  font-size: 10px;
}
.arc-timeline-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 3px 6px;
}
.theme-dark .arc-timeline-item {
  background: #1e293b;
  border-color: #334155;
}
.arc-ep-tag {
  font-family: monospace;
  font-weight: 700;
  color: #7c3aed;
}
.theme-dark .arc-ep-tag {
  color: #c084fc;
}
.arc-text {
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.theme-dark .arc-text {
  color: #cbd5e1;
}

/* 伏笔回收看板 */
.clue-closure-audit-block {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.theme-dark .clue-closure-audit-block {
  background: #0f172a;
  border-color: #334155;
}
.clue-audit-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.clue-title-part {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .clue-title-part {
  color: #f8fafc;
}
.clue-count-part {
  font-size: 11px;
  color: #64748b;
}
.theme-dark .clue-count-part {
  color: #94a3b8;
}

.clue-stats-quad-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.clue-stat-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.theme-dark .clue-stat-card {
  background: #1e293b;
  border-color: #334155;
}
.clue-stat-card .c-lbl { font-size: 10px; color: #64748b; }
.clue-stat-card .c-val { font-size: 14px; font-weight: 800; font-family: monospace; }
.clue-stat-card .c-val.green { color: #10b981; }
.clue-stat-card .c-val.orange { color: #f59e0b; }
.clue-stat-card .c-val.red { color: #e11d48; }

.clue-items-list-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.clue-item-row-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 11px;
}
.theme-dark .clue-item-row-card {
  background: #1e293b;
  border-color: #334155;
}
.clue-id-badge {
  font-family: monospace;
  font-weight: 700;
  color: #7c3aed;
  width: 75px;
}
.theme-dark .clue-id-badge {
  color: #c084fc;
}
.clue-name-and-path {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.c-main-name {
  font-weight: 700;
  color: #0f172a;
}
.theme-dark .c-main-name {
  color: #f8fafc;
}
.c-path-text {
  font-size: 10px;
  color: #64748b;
}
.theme-dark .c-path-text {
  color: #94a3b8;
}
.clue-status-end-box {
  display: flex;
  align-items: center;
  gap: 12px;
}
.clue-ep-range {
  font-family: monospace;
  color: #64748b;
}
.clue-status-pill {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}
.clue-status-pill.recovered {
  background: #dcfce7;
  color: #15803d;
}
.theme-dark .clue-status-pill.recovered {
  background: #064e3b;
  color: #86efac;
}
.clue-status-pill.pending {
  background: #fef3c7;
  color: #b45309;
}
.theme-dark .clue-status-pill.pending {
  background: #78350f;
  color: #fde68a;
}
.clue-status-pill.unrecovered {
  background: #fee2e2;
  color: #b91c1c;
}
.theme-dark .clue-status-pill.unrecovered {
  background: #7f1d1d;
  color: #fca5a5;
}
.clue-heal-hint {
  font-size: 9px;
  text-decoration: underline;
}

/* 5. 视听资产就绪看板 */
.visual-bridge-two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.bridge-left-col, .bridge-right-col {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.theme-dark .bridge-left-col, .theme-dark .bridge-right-col {
  background: #0f172a;
  border-color: #334155;
}
.sub-block-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sub-blk-title {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .sub-blk-title {
  color: #f8fafc;
}
.sub-blk-tag {
  font-size: 10.5px;
  color: #64748b;
}

.pipeline-progress-bars-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pipe-bar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
}
.pipe-lbl {
  width: 90px;
  color: #334155;
  font-weight: 600;
}
.theme-dark .pipe-lbl {
  color: #cbd5e1;
}
.pipe-track {
  flex: 1;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}
.theme-dark .pipe-track {
  background: #334155;
}
.pipe-fill {
  height: 100%;
  background: #7c3aed;
}
.pipe-fill.green-full {
  background: #10b981;
}
.pipe-count {
  width: 60px;
  text-align: right;
  font-family: monospace;
  color: #64748b;
}
.pipe-count.green {
  color: #10b981;
  font-weight: 800;
}
.pipe-desc-note, .shot-dist-note, .music-cues-note {
  font-size: 10.5px;
  color: #64748b;
  line-height: 1.4;
}
.theme-dark .pipe-desc-note, .theme-dark .shot-dist-note, .theme-dark .music-cues-note {
  color: #94a3b8;
}

.shot-dist-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}
.shot-dist-title {
  font-size: 12px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .shot-dist-title {
  color: #f8fafc;
}
.shot-dist-tag { font-size: 10px; color: #64748b; }
.shot-dist-bars-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.shot-dist-bar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
}
.s-type-lbl { width: 70px; color: #334155; }
.theme-dark .s-type-lbl { color: #cbd5e1; }
.s-track {
  flex: 1;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}
.theme-dark .s-track { background: #334155; }
.s-fill { height: 100%; }
.s-pct-val { width: 40px; text-align: right; font-family: monospace; font-weight: 700; }

.music-cues-cards-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.music-cue-item-card {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 11px;
}
.theme-dark .music-cue-item-card {
  background: #1e293b;
  border-color: #334155;
}
.mc-icon { font-size: 13px; }
.mc-ep-tag { font-family: monospace; font-weight: 800; color: #7c3aed; }
.theme-dark .mc-ep-tag { color: #c084fc; }
.mc-action-title { font-weight: 700; color: #0f172a; width: 70px; }
.theme-dark .mc-action-title { color: #f8fafc; }
.mc-motif-desc { flex: 1; color: #475569; }
.theme-dark .mc-motif-desc { color: #cbd5e1; }
.mc-bpm-tag, .mc-duration-tag {
  font-family: monospace;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #64748b;
}
.theme-dark .mc-bpm-tag, .theme-dark .mc-duration-tag {
  background: #334155;
  color: #cbd5e1;
}

/* 底部常驻核心操作交互栏 (Sticky Bottom) */
.stage5-sticky-bottom-bar {
  position: fixed;
  bottom: 0;
  left: 200px; /* 侧边栏宽度 */
  right: 0;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  box-shadow: 0 -4px 12px rgba(0,0,0,0.06);
  padding: 12px 24px;
  z-index: 100;
}
.theme-dark .stage5-sticky-bottom-bar {
  background: #1e293b;
  border-top-color: #334155;
}
.bottom-interact-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 1400px;
  margin: 0 auto;
}
.bottom-warning-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.warn-icon-box {
  font-size: 20px;
}
.warn-text-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.warn-main-title {
  font-size: 13px;
  font-weight: 800;
  color: #0f172a;
}
.theme-dark .warn-main-title {
  color: #f8fafc;
}
.warn-sub-msg {
  font-size: 11px;
  color: #64748b;
}
.theme-dark .warn-sub-msg {
  color: #94a3b8;
}

.bottom-action-buttons-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.btn-report {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
}
.btn-lock-freeze {
  background: #7c3aed !important;
  border-color: #7c3aed !important;
}
.btn-goto-canvas {
  background: #10b981 !important;
  border-color: #10b981 !important;
}

.bottom-checklist-pills-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.check-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}
.check-pill.green { background: #dcfce7; color: #15803d; }
.check-pill.orange { background: #ffedd5; color: #c2410c; }
.check-pill.red { background: #fee2e2; color: #b91c1c; }
.check-pill.gray { background: #f1f5f9; color: #64748b; }
.theme-dark .check-pill.green { background: #064e3b; color: #86efac; }
.theme-dark .check-pill.orange { background: #7c2d12; color: #fdba74; }
.theme-dark .check-pill.red { background: #7f1d1d; color: #fca5a5; }
.theme-dark .check-pill.gray { background: #334155; color: #cbd5e1; }
.chk-mark { font-weight: 800; }

/* 导出中心与单集自愈弹窗 */
.export-summary-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 14px;
}
.theme-dark .export-summary-box {
  background: #0f172a;
  border-color: #334155;
}
.ex-name { font-weight: 800; font-size: 13px; color: #0f172a; margin-bottom: 2px; }
.theme-dark .ex-name { color: #f8fafc; }
.ex-meta { font-size: 11px; color: #64748b; }
.theme-dark .ex-meta { color: #94a3b8; }

.export-files-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.export-file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
}
.theme-dark .export-file-item {
  background: #1e293b;
  border-color: #334155;
}
.f-icon { font-size: 18px; margin-right: 8px; }
.f-info { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.f-title { font-size: 12px; color: #0f172a; }
.theme-dark .f-title { color: #f8fafc; }
.f-size { font-size: 10.5px; color: #94a3b8; }

.ep-heal-score-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
  font-size: 13px;
}
.ep-heal-score-row strong.red { color: #e11d48; }
.ep-heal-score-row strong.green { color: #10b981; }
.ep-heal-tip {
  font-size: 12px;
  color: #b45309;
  background: #fef3c7;
  padding: 8px 12px;
  border-radius: 6px;
  line-height: 1.5;
}
.ep-heal-tip.green-tip {
  color: #15803d;
  background: #dcfce7;
}
.theme-dark .ep-heal-tip {
  background: #78350f;
  color: #fde68a;
}
.theme-dark .ep-heal-tip.green-tip {
  background: #064e3b;
  color: #86efac;
}
</style>

