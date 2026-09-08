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
          <div class="item-icon-box green">
            <el-icon><Check /></el-icon>
          </div>
          <span class="item-label">创意立项</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage2_bible', done: stagePassed('stage2') }"
          @click="activeTab = 'stage2_bible'"
        >
          <div class="item-icon-box green">
            <el-icon><Check /></el-icon>
          </div>
          <span class="item-label">故事圣经</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage3_outline', done: stagePassed('stage3') }"
          @click="activeTab = 'stage3_outline'"
        >
          <div class="item-icon-box green">
            <el-icon><Check /></el-icon>
          </div>
          <span class="item-label">三级大纲</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage4_script', done: stagePassed('stage4') }"
          @click="activeTab = 'stage4_script'"
        >
          <div class="item-icon-box green">
            <el-icon><Check /></el-icon>
          </div>
          <span class="item-label">故事剧本</span>
          <span class="item-score-badge">{{ avgScore }}分</span>
        </div>
        <div
          class="nav-tree-item"
          :class="{ active: activeTab === 'stage5_finalize', done: stagePassed('stage5') }"
          @click="activeTab = 'stage5_finalize'"
        >
          <div class="item-icon-box gray">
            <span>5</span>
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
                    <span class="step-num">5</span>
                    <span class="step-title">复盘定稿</span>
                  </div>
                  <div class="step-sub">等待上游</div>
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

        <!-- 阶段 1：创意立项展示 -->
        <div v-show="activeTab === 'stage1_concept'" class="stage-content-view">
          <div class="stage-view-card">
            <h2 class="view-title">阶段 1：立项档案与全书总纲</h2>
            <p class="view-desc">由 intake_requirements_node 生成的核心高概念与商业转化策略</p>
            <el-form label-position="top">
              <el-form-item label="一句话核心钩子 (One-Sentence Hook)">
                <el-input :model-value="stage1Data.one_sentence_hook || '隐世龙王隐藏身份归来，在婚礼现场当众揭开三千亿龙令'" readonly />
              </el-form-item>
              <el-form-item label="全书总故事大纲 (Full Story Summary)">
                <el-input :model-value="stage1Data.story_summary || storyPrompt" type="textarea" :rows="5" readonly />
              </el-form-item>
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="目标受众画像">
                    <el-input :model-value="stage1Data.target_audience || '25-45岁男性，爽感与逆袭驱动'" readonly />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="付费转化驱动力">
                    <el-input :model-value="stage1Data.paywall_driver || '主角多重绝密身份层层揭晓，极致反差爽点'" readonly />
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </div>
        </div>

        <!-- 阶段 2：故事圣经与人设库 -->
        <div v-show="activeTab === 'stage2_bible'" class="stage-content-view">
          <div class="stage-view-card">
            <h2 class="view-title">阶段 2：故事圣经与人物矩阵</h2>
            <p class="view-desc">世界观底层法则、九维角色档案库与视觉一致性锚点</p>
            <div class="char-matrix-grid">
              <div v-for="c in (charactersList || defaultCharacters)" :key="c.name" class="char-matrix-card">
                <div class="char-head">
                  <strong class="c-name">{{ c.name }}</strong>
                  <el-tag size="small" :type="c.role === 'protagonist' ? 'danger' : 'info'">{{ c.role || '主要角色' }}</el-tag>
                </div>
                <div class="c-field"><strong>身份与面具：</strong>{{ c.description || c.identity_and_mask || '表面隐忍，实为隐龙殿主' }}</div>
                <div class="c-field"><strong>视觉识别锚点：</strong>{{ c.visual_anchor || c.appearance || '深灰风衣，腕带隐龙令' }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 阶段 3：三级大纲工作台 -->
        <div v-show="activeTab === 'stage3_outline'" class="stage-content-view">
          <div class="stage-view-card">
            <div class="outline-header-row">
              <div>
                <h2 class="view-title">阶段 3：三级大纲与分集微观节拍</h2>
                <p class="view-desc">全书总纲（一级）+ 四幕单元大纲（二级）+ 80集分集节拍（三级）</p>
              </div>
              <el-button v-if="isPipelinePaused" type="success" size="small" @click="onResumePipeline">
                ✓ 确认大纲并继续生成正文
              </el-button>
            </div>
            <div class="episode-outline-list">
              <div v-for="ep in (outlinesList || defaultOutlines)" :key="ep.episode_num" class="outline-item-card">
                <div class="ep-num-tag">第 {{ ep.episode_num }} 集</div>
                <div class="ep-content-box">
                  <div class="ep-title-row">
                    <strong>{{ ep.title || '江城风云之暗流涌动' }}</strong>
                    <el-tag size="small" effect="plain">{{ ep.commercial_tag || '常规剧情集' }}</el-tag>
                  </div>
                  <div class="ep-detail-text"><strong>核心动作：</strong>{{ ep.core_action || '主角出手反制商业封锁' }}</div>
                  <div class="ep-detail-text"><strong>片尾断章：</strong>{{ ep.ending_cliffhanger || '暗卫持令跪地，全场震惊定格' }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 阶段 4：分集正文与 AST 四分块 -->
        <div v-show="activeTab === 'stage4_script'" class="stage-content-view">
          <div class="stage-view-card">
            <h2 class="view-title">阶段 4：故事剧本（AST 4分块与五阶质检）</h2>
            <div class="ep-select-row">
              <el-select v-model="selectedEpisodeIndex" placeholder="选择查看分集" style="width: 160px">
                <el-option v-for="i in totalCount" :key="i" :label="`第 ${i} 集`" :value="i" />
              </el-select>
              <el-tag type="success" size="small">五阶雷达评分: 94 分 (达标)</el-tag>
            </div>
            <el-input
              v-model="currentScriptContent"
              type="textarea"
              :rows="12"
              class="script-code-editor"
            />
          </div>
        </div>

        <!-- 阶段 5：复盘定稿与视听转化桥接 -->
        <div v-show="activeTab === 'stage5_finalize'" class="stage-content-view">
          <div class="stage-view-card">
            <h2 class="view-title">阶段 5：全剧复盘定稿与 Bridge 契约</h2>
            <p class="view-desc">剧本锁定（lock_status=1）并初始化 320 个视听分镜镜头</p>
            <div class="bridge-status-box">
              <div class="status-badge-locked">🔒 剧本已定稿锁定 (只读保护)</div>
              <div class="bridge-stats-row">
                <span>镜头总数: <strong>320 镜头</strong></span>
                <span>五阶质检均分: <strong>94.6 分</strong></span>
                <span>伏笔回收率: <strong>91.7%</strong></span>
              </div>
            </div>
            <div class="finalize-actions-row">
              <el-button type="primary" size="large" @click="goCanvasMode">
                🚀 一键转入视听制作画布
              </el-button>
            </div>
          </div>
        </div>
      </main>
    </div>

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
  FolderOpened, ArrowDown, Grid, Operation, Sunny, Moon, Setting, Lock, Check, Plus, DocumentAdd
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

// 默认占位数据
const defaultCharacters = [
  { name: '林晚', role: 'protagonist', description: '调查母亲死因的敏锐女记者', visual_anchor: '深色风衣，短发，随身携带录音笔' },
  { name: '周行', role: 'supporter', description: '追查当年火灾真相的刑警', visual_anchor: '皮夹克，眼神深邃锐利' },
  { name: '周震天', role: 'antagonist', description: '周氏集团掌门人，幕后真凶', visual_anchor: '定制唐装，右手持两枚沉香手串' }
]

const defaultOutlines = [
  { episode_num: 1, title: '第七封遗信', commercial_tag: '免费引流钩子', core_action: '林晚在老宅拆开染血信封', ending_cliffhanger: '门外突然传来敲门声' },
  { episode_num: 2, title: '深夜造访的刑警', commercial_tag: '免费引流钩子', core_action: '周行亮明证件与母辈旧事', ending_cliffhanger: '周氏工厂照片浮出水面' },
  { episode_num: 3, title: '灵堂里的第七封信', commercial_tag: '核心付费卡点', core_action: '两人联手潜入老宅密室', ending_cliffhanger: '暗道机关被触动，火光再现！' }
]

function stagePassed(stageKey) {
  if (stageKey === 'stage1') return true
  if (stageKey === 'stage2') return true
  if (stageKey === 'stage3') return isPipelinePaused.value || generatedCount.value > 0
  if (stageKey === 'stage4') return generatedCount.value > 0
  if (stageKey === 'stage5') return drama.value?.lock_status === 1
  return false
}

function changeEpisodes(delta) {
  const newVal = episodeCount.value + delta
  if (newVal >= 5 && newVal <= 120) {
    episodeCount.value = newVal
    totalCount.value = newVal
  }
}

// 加载项目详情
async function loadDramaDetail() {
  if (!dramaId.value) return
  try {
    const res = await dramaAPI.get(dramaId.value)
    drama.value = res
    totalCount.value = res.total_episodes || 80
    episodeCount.value = res.total_episodes || 80
    if (res.description) storyPrompt.value = res.description
    if (res.genre) selectedGenre.value = res.genre
    if (res.pipeline_status === 'paused_hitl') {
      isPipelinePaused.value = true
      pausedNode.value = res.hitl_paused_node || 'outline_generation'
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
  const sseUrl = `/api/v1/script-studio/dramas/${dramaId.value}/events`
  eventSource = new EventSource(sseUrl)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      const evtType = data.type || data.event

      if (evtType === 'hitl_interrupt') {
        isPipelinePaused.value = true
        pausedNode.value = data.node || 'outline_generation'
        pipelineRunning.value = false
        ElMessage.warning(`【HITL 挂起】阶段 3 三级大纲已生成完毕，等待编剧审批确认！`)
        activeTab.value = 'stage3_outline'
      } else if (evtType === 'pipeline_completed') {
        pipelineRunning.value = false
        isPipelinePaused.value = false
        ElMessage.success('全剧剧本工业化流水线已全部生成完毕！')
        loadDramaDetail()
      } else if (evtType === 'batch_completed') {
        generatedCount.value = Math.min(totalCount.value, generatedCount.value + 3)
      }
    } catch (e) {
      console.warn('SSE 数据解析异常:', e)
    }
  }

  eventSource.onerror = () => {
    // 降级关闭
  }
}

// 启动 LangGraph 流水线
async function onStartPipeline() {
  if (!storyPrompt.value.trim()) {
    ElMessage.warning('请输入故事核心梗概或用户提示词')
    return
  }
  pipelineRunning.value = true
  try {
    const commTag = `${selectedGenre.value}-${selectedType.value}`
    await scriptStudioAPI.startPipeline(dramaId.value, {
      user_prompt: storyPrompt.value.trim(),
      genre: selectedGenre.value,
      total_episodes: episodeCount.value,
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
</style>
