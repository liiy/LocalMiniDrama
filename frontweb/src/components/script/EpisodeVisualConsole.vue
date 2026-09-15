<template>
  <div class="episode-visual-console">
    <!-- 控制台顶栏：集数切换与概览 -->
    <div class="console-header">
      <div class="header-left">
        <el-tag type="primary" size="large" effect="dark" class="stage-badge">第二程 · 视听分镜工程</el-tag>
        <span class="ep-selector-label">第</span>
        <el-input-number
          v-model="currentEp"
          :min="1"
          :max="totalEpisodes"
          size="small"
          @change="loadVisualPackage"
        />
        <span class="ep-selector-label">集 / 共 {{ totalEpisodes }} 集</span>
        <el-button size="small" type="primary" plain @click="loadVisualPackage" :loading="loading">
          刷新工程包
        </el-button>
      </div>

      <div class="header-right">
        <el-tag v-if="visualPackage.manifest" type="success" size="small" effect="plain">
          真理源资产: {{ assetTotalCount }} 个
        </el-tag>
        <el-tag v-if="visualPackage.storyboards?.length" type="warning" size="small" effect="plain">
          分镜镜头: {{ visualPackage.storyboards.length }} 个
        </el-tag>
        <el-tag v-if="visualPackage.audio_mastering" type="info" size="small" effect="plain">
          音频总长: {{ visualPackage.audio_mastering.total_duration_sec || 120 }}s
        </el-tag>
      </div>
    </div>

    <!-- 阶段 6：单集资产真理源引单卡片 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="card-header-bar">
          <span class="card-title">📦 阶段 6 · 单集资产提纯引单 (Truth Source)</span>
          <span class="card-sub">锁定复用 APPROVED 资产，隔离待生成新资产</span>
        </div>
      </template>

      <div class="manifest-grid">
        <div class="manifest-col">
          <div class="col-title">已核准出场角色 ({{ visualPackage.manifest?.approved_character_ids?.length || 0 }})</div>
          <div class="tags-container">
            <el-tag
              v-for="id in visualPackage.manifest?.approved_character_ids || []"
              :key="'char_' + id"
              type="success"
              size="small"
            >
              角色 ID: {{ id }}
            </el-tag>
            <span v-if="!visualPackage.manifest?.approved_character_ids?.length" class="empty-text">无入场角色</span>
          </div>
        </div>

        <div class="manifest-col">
          <div class="col-title">已核准场景空间 ({{ visualPackage.manifest?.approved_scene_ids?.length || 0 }})</div>
          <div class="tags-container">
            <el-tag
              v-for="id in visualPackage.manifest?.approved_scene_ids || []"
              :key="'scene_' + id"
              type="info"
              size="small"
            >
              场景 ID: {{ id }}
            </el-tag>
            <span v-if="!visualPackage.manifest?.approved_scene_ids?.length" class="empty-text">无场景引单</span>
          </div>
        </div>

        <div class="manifest-col">
          <div class="col-title">关键反转物证 ({{ visualPackage.manifest?.approved_prop_ids?.length || 0 }})</div>
          <div class="tags-container">
            <el-tag
              v-for="id in visualPackage.manifest?.approved_prop_ids || []"
              :key="'prop_' + id"
              type="warning"
              size="small"
            >
              物证 ID: {{ id }}
            </el-tag>
            <span v-if="!visualPackage.manifest?.approved_prop_ids?.length" class="empty-text">无物证道具</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 阶段 7：视听导演双模式分镜与毫秒级 SRT 卡片 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="card-header-bar">
          <span class="card-title">🎬 阶段 7 · 视听导演双模式分镜执行表</span>
          <div class="header-tools">
            <el-button size="small" type="primary" plain @click="showSrtDialog = true">
              查看 SRT 字幕轨
            </el-button>
          </div>
        </div>
      </template>

      <!-- 分镜卡片流 -->
      <div v-if="visualPackage.storyboards?.length" class="storyboard-list">
        <div
          v-for="shot in visualPackage.storyboards"
          :key="'shot_' + shot.shot_id"
          class="shot-card"
        >
          <div class="shot-header">
            <span class="shot-num">#{{ shot.shot_id }}</span>
            <el-tag size="small" effect="plain" type="primary">{{ shot.timecode }}</el-tag>
            <el-tag size="small" :type="shot.generation_mode === 'first_last_frame' ? 'success' : 'warning'">
              {{ shot.generation_mode === 'first_last_frame' ? '模式 A: 首尾帧' : '模式 B: 多图参考' }}
            </el-tag>
            <span class="shot-duration">{{ shot.duration_sec }}s</span>
            <span class="shot-motion">{{ shot.framing }} · {{ shot.camera_motion }}</span>
          </div>

          <div class="shot-body">
            <!-- 模式 A 首尾帧展示 -->
            <div v-if="shot.generation_mode === 'first_last_frame'" class="mode-content mode-a">
              <div class="frame-prompt">
                <span class="label">首帧 Prompt:</span>
                <span class="val">{{ shot.first_last_config?.first_frame_prompt || '—' }}</span>
              </div>
              <div class="frame-prompt">
                <span class="label">尾帧 Prompt:</span>
                <span class="val">{{ shot.first_last_config?.last_frame_prompt || '—' }}</span>
              </div>
              <div class="frame-prompt">
                <span class="label">运镜描述:</span>
                <span class="val">{{ shot.first_last_config?.video_motion_prompt || '—' }}</span>
              </div>
            </div>

            <!-- 模式 B 多图参考展示 -->
            <div v-else class="mode-content mode-b">
              <div class="frame-prompt">
                <span class="label">参考资产:</span>
                <span class="val">{{ shot.multi_image_config?.reference_image_assets?.join(', ') || '—' }}</span>
              </div>
              <div class="frame-prompt">
                <span class="label">动态提示词:</span>
                <span class="val">{{ shot.multi_image_config?.video_prompt || '—' }}</span>
              </div>
            </div>

            <!-- 选型判定理由 -->
            <div class="rationale-bar">
              <span class="label">选型依据:</span>
              <span class="val">{{ shot.selection_rationale }}</span>
            </div>

            <!-- 对白与口型动力学 -->
            <div v-if="shot.audio?.dialogue" class="dialogue-bar">
              <span class="dialogue-text">🗣️ “{{ shot.audio.dialogue }}”</span>
              <div v-if="shot.lipsync_dynamics" class="lipsync-indicator">
                <span class="viseme">音素: {{ shot.lipsync_dynamics.viseme }}</span>
                <div class="jaw-meter">
                  <div
                    class="jaw-fill"
                    :style="{ width: Math.round((shot.lipsync_dynamics.jaw_open || 0.5) * 100) + '%' }"
                  ></div>
                </div>
                <span class="jaw-val">开口度: {{ Math.round((shot.lipsync_dynamics.jaw_open || 0) * 100) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty-block">暂无分镜数据，请先生成第二程视听工程</div>
    </el-card>

    <!-- 阶段 8：全息声学混音工程与响度避让 -->
    <el-card class="section-card" shadow="never">
      <template #header>
        <div class="card-header-bar">
          <span class="card-title">🔊 阶段 8 · 全息声学混音工程与避让卡点</span>
          <span class="card-sub">对白侧链避让 (-12dB Ducking) 与微反转断崖静音 (-inf dB)</span>
        </div>
      </template>

      <div v-if="visualPackage.audio_mastering" class="audio-master-body">
        <!-- 侧链避让卡点清单 -->
        <div class="audio-block">
          <div class="block-title">侧链避让 Ducking 卡点 ({{ visualPackage.audio_mastering.ducking_events?.length || 0 }})</div>
          <div class="ducking-list">
            <div
              v-for="(ev, idx) in visualPackage.audio_mastering.ducking_events || []"
              :key="'duck_' + idx"
              class="ducking-item"
            >
              <span class="time-range">{{ ev.start_sec }}s - {{ ev.end_sec }}s</span>
              <el-tag size="small" type="danger" effect="plain">{{ ev.gain_db }} dB</el-tag>
              <span class="target-track">{{ ev.target_track }}</span>
              <span class="desc">{{ ev.description }}</span>
            </div>
            <div v-if="!visualPackage.audio_mastering.ducking_events?.length" class="empty-text">
              本集无对白避让卡点
            </div>
          </div>
        </div>

        <!-- 剪辑 NLE 轨道指南 -->
        <div class="audio-block">
          <div class="block-title">剪映 / Premiere 多轨音频指南</div>
          <div class="nle-tracks">
            <div class="track-row">
              <span class="track-id">Track A1</span>
              <span class="track-type">人声对白轨</span>
              <span class="track-loudness">标准化 -23 LUFS</span>
            </div>
            <div class="track-row">
              <span class="track-id">Track A2</span>
              <span class="track-type">拟音与物证 Foleys</span>
              <span class="track-loudness">增益 +2.5dB ~ +3.0dB</span>
            </div>
            <div class="track-row">
              <span class="track-id">Track A3</span>
              <span class="track-type">Leitmotif 背景音乐</span>
              <span class="track-loudness">动态避让 (-12dB Ducking)</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty-block">暂无音频混音工程数据</div>
    </el-card>

    <!-- SRT 字幕轨弹窗 -->
    <el-dialog v-model="showSrtDialog" title="SRT 毫秒级字幕轴测" width="600px">
      <pre class="srt-content-box">{{ visualPackage.srt_export || '暂无字幕内容' }}</pre>
      <template #footer>
        <el-button @click="showSrtDialog = false">关闭</el-button>
        <el-button type="primary" @click="copySrt">复制字幕文本</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { scriptStudioAPI } from '@/api/scriptStudio'

const props = defineProps({
  dramaId: {
    type: [Number, String],
    required: true
  },
  totalEpisodes: {
    type: Number,
    default: 12
  }
})

const currentEp = ref(1)
const loading = ref(false)
const showSrtDialog = ref(false)
const visualPackage = ref({
  manifest: null,
  storyboards: [],
  srt_export: '',
  audio_mastering: null
})

const assetTotalCount = computed(() => {
  const m = visualPackage.value.manifest
  if (!m) return 0
  return (
    (m.approved_character_ids?.length || 0) +
    (m.approved_scene_ids?.length || 0) +
    (m.approved_prop_ids?.length || 0)
  )
})

async function loadVisualPackage() {
  if (!props.dramaId) return
  loading.value = true
  try {
    const res = await scriptStudioAPI.getEpisodeVisualPackage(props.dramaId, currentEp.value)
    if (res.data) {
      visualPackage.value = res.data
    }
  } catch (err) {
    ElMessage.error(err.message || '加载视听工程包失败')
  } finally {
    loading.value = false
  }
}

function copySrt() {
  if (!visualPackage.value.srt_export) {
    ElMessage.warning('暂无可复制的字幕文本')
    return
  }
  navigator.clipboard.writeText(visualPackage.value.srt_export)
  ElMessage.success('SRT 字幕文本已复制到剪贴板！')
}

onMounted(() => {
  loadVisualPackage()
})
</script>

<style scoped>
.episode-visual-console {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 12px;
}

.console-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--el-bg-color-overlay);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-light);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stage-badge {
  font-weight: bold;
}

.ep-selector-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.section-card {
  border-radius: 8px;
}

.card-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.card-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.manifest-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.manifest-col {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 6px;
}

.col-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.storyboard-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.shot-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 12px;
  background: var(--el-bg-color-overlay);
}

.shot-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.shot-num {
  font-weight: bold;
  color: var(--el-color-primary);
}

.shot-duration {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}

.shot-motion {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.shot-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mode-content {
  background: var(--el-fill-color-lighter);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.frame-prompt {
  display: flex;
  gap: 6px;
}

.frame-prompt .label {
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.frame-prompt .val {
  color: var(--el-text-color-primary);
}

.rationale-bar {
  font-size: 12px;
  color: var(--el-color-info-dark-2);
  display: flex;
  gap: 6px;
}

.dialogue-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(64, 158, 255, 0.06);
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 12px;
}

.dialogue-text {
  font-weight: 500;
  color: var(--el-color-primary);
}

.lipsync-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.jaw-meter {
  width: 60px;
  height: 6px;
  background: var(--el-border-color-light);
  border-radius: 3px;
  overflow: hidden;
}

.jaw-fill {
  height: 100%;
  background: var(--el-color-success);
  transition: width 0.3s ease;
}

.audio-master-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.audio-block {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px;
}

.block-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--el-text-color-primary);
}

.ducking-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ducking-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  background: var(--el-bg-color-overlay);
  padding: 6px 8px;
  border-radius: 4px;
}

.time-range {
  font-family: monospace;
  font-weight: bold;
}

.nle-tracks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.track-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--el-bg-color-overlay);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
}

.track-id {
  font-weight: bold;
  color: var(--el-color-primary);
}

.empty-block {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 24px 0;
  font-size: 13px;
}

.srt-content-box {
  background: #1e1e1e;
  color: #00ff66;
  padding: 12px;
  border-radius: 6px;
  max-height: 360px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
  line-height: 1.5;
}
</style>
