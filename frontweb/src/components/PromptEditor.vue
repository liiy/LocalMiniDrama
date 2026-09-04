<template>
  <div class="prompt-editor-page">
    <div v-if="loading" v-loading="true" class="loading-wrap" />
    <template v-else>
      <div class="editor-layout">
        <!-- 左侧菜单 -->
        <div class="left-sidebar">
          <div class="sidebar-menu">
            <div
              v-for="p in prompts"
              :key="p.key"
              :class="['menu-item', { active: currentKey === p.key }]"
              @click="selectPrompt(p.key)"
            >
              <div class="menu-item-content">
                <span class="menu-label">{{ p.label }}</span>
                <el-tag
                  v-if="p.is_customized"
                  type="warning"
                  size="small"
                  class="menu-tag"
                >已自定义</el-tag>
                <el-tag v-else type="info" size="small" class="menu-tag">默认</el-tag>
              </div>
              <div v-if="isDirty[p.key]" class="dirty-indicator" />
            </div>
          </div>
        </div>

        <!-- 右侧编辑区 -->
        <div class="right-content">
          <p class="page-desc">
            可自定义 AI 生成各阶段使用的提示词（System Prompt）。蓝色锁定区为 JSON
            格式要求，不可修改以确保输出格式正确。
          </p>

          <div v-if="currentPrompt" class="prompt-card">
            <div class="prompt-card-header">
              <div class="prompt-card-meta">
                <span class="prompt-label">{{ currentPrompt.label }}</span>
                <el-tag
                  v-if="currentPrompt.is_customized"
                  type="warning"
                  size="small"
                  class="custom-tag"
                >已自定义</el-tag>
                <el-tag v-else type="info" size="small" class="custom-tag">使用默认</el-tag>
              </div>
              <p class="prompt-desc">{{ currentPrompt.description }}</p>
            </div>

            <div class="prompt-edit-section">
              <div class="section-label">
                <el-icon class="section-icon"><Edit /></el-icon>
                <span>指令内容（可编辑）</span>
              </div>
              <el-input
                v-model="editState[currentPrompt.key]"
                type="textarea"
                :rows="16"
                :placeholder="currentPrompt.default_body"
                class="prompt-textarea"
                @input="markDirty(currentPrompt.key)"
              />
            </div>

            <div v-if="currentPrompt.locked_suffix" class="prompt-locked-section">
              <div class="section-label section-label--locked">
                <el-icon class="section-icon"><Lock /></el-icon>
                <span>JSON 格式要求（锁定，不可修改）</span>
              </div>
              <div class="locked-content">{{ currentPrompt.locked_suffix }}</div>
            </div>

            <div class="prompt-actions">
              <el-button
                size="small"
                @click="openHistoryDialog(currentPrompt)"
              >
                <el-icon><Clock /></el-icon>
                版本历史与回滚
              </el-button>
              <el-button
                size="small"
                @click="openRunsDrawer(currentPrompt)"
              >
                <el-icon><Document /></el-icon>
                执行审计与快照
              </el-button>
              <el-button
                type="primary"
                size="small"
                :loading="savingKey === currentPrompt.key"
                :disabled="!isDirty[currentPrompt.key]"
                @click="save(currentPrompt)"
              >
                保存
              </el-button>
              <el-button
                size="small"
                :loading="resettingKey === currentPrompt.key"
                :disabled="!currentPrompt.is_customized && !isDirty[currentPrompt.key]"
                @click="reset(currentPrompt)"
              >
                恢复默认
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 版本历史抽屉 -->
    <el-drawer
      v-model="historyDrawerVisible"
      :title="`版本历史 - ${activePromptForModal?.label || ''}`"
      size="560px"
    >
      <div v-loading="historyLoading" class="drawer-body">
        <el-table :data="historyList" stripe style="width: 100%">
          <el-table-column prop="version" label="版本" width="80">
            <template #default="{ row }">
              v{{ row.version }}
              <el-tag v-if="row.status === 'active'" size="small" type="success">当前</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="150" />
          <el-table-column prop="status" label="状态" width="85" />
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                @click="previewHistoryVersion(row)"
              >
                查看
              </el-button>
              <el-button
                v-if="row.status !== 'active'"
                link
                type="warning"
                size="small"
                @click="rollbackToVersion(row)"
              >
                回滚
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="selectedHistoryVersion" class="history-preview-box">
          <div class="preview-header">
            <strong>版本 v{{ selectedHistoryVersion.version }} 详情预览</strong>
          </div>
          <el-input
            :model-value="selectedHistoryVersion.template_body"
            type="textarea"
            :rows="8"
            readonly
          />
        </div>
      </div>
    </el-drawer>

    <!-- Prompt Runs 审计与调用快照抽屉 -->
    <el-drawer
      v-model="runsDrawerVisible"
      :title="`执行审计记录 - ${activePromptForModal?.label || ''}`"
      size="650px"
    >
      <div v-loading="runsLoading" class="drawer-body">
        <el-table :data="runsList" stripe style="width: 100%">
          <el-table-column prop="id" label="Run ID" width="80" />
          <el-table-column prop="latency_ms" label="耗时" width="90">
            <template #default="{ row }">
              {{ row.latency_ms ? row.latency_ms + ' ms' : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="total_tokens" label="Tokens" width="90">
            <template #default="{ row }">
              {{ (row.prompt_tokens || 0) + (row.completion_tokens || 0) || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="执行时间" min-width="150" />
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="viewRunDetail(row)">
                快照
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="selectedRun" class="run-detail-box">
          <div class="preview-header">
            <strong>Run #{{ selectedRun.id }} 调用详情与上下文快照</strong>
          </div>
          <div class="run-detail-tabs">
            <el-tabs v-model="runTab">
              <el-tab-pane label="最终 Prompt" name="prompt">
                <el-input
                  :model-value="selectedRun.final_prompt || selectedRun.prompt_text"
                  type="textarea"
                  :rows="6"
                  readonly
                />
              </el-tab-pane>
              <el-tab-pane label="原始输出" name="raw">
                <el-input
                  :model-value="selectedRun.raw_output || selectedRun.response_text"
                  type="textarea"
                  :rows="6"
                  readonly
                />
              </el-tab-pane>
              <el-tab-pane label="解析结果" name="parsed">
                <el-input
                  :model-value="JSON.stringify(selectedRun.parsed_output || {}, null, 2)"
                  type="textarea"
                  :rows="6"
                  readonly
                />
              </el-tab-pane>
              <el-tab-pane label="上下文快照" name="context">
                <el-input
                  :model-value="JSON.stringify(selectedRun.context_snapshot || {}, null, 2)"
                  type="textarea"
                  :rows="6"
                  readonly
                />
              </el-tab-pane>
            </el-tabs>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Lock, Clock, Document } from '@element-plus/icons-vue'
import { promptsAPI } from '@/api/prompts'

const loading = ref(false)
const prompts = ref([])
const editState = ref({})
const isDirty = ref({})
const savingKey = ref(null)
const resettingKey = ref(null)
const currentKey = ref(null)

// 历史版本与审计抽屉状态
const historyDrawerVisible = ref(false)
const historyLoading = ref(false)
const historyList = ref([])
const selectedHistoryVersion = ref(null)

const runsDrawerVisible = ref(false)
const runsLoading = ref(false)
const runsList = ref([])
const selectedRun = ref(null)
const runTab = ref('prompt')
const activePromptForModal = ref(null)

const currentPrompt = computed(() => {
  return prompts.value.find((p) => p.key === currentKey.value)
})

async function load() {
  loading.value = true
  try {
    const data = await promptsAPI.list()
    prompts.value = data.prompts || []
    for (const p of prompts.value) {
      editState.value[p.key] = p.current_body || p.default_body
    }
    // 默认选中第一个
    if (prompts.value.length > 0) {
      currentKey.value = prompts.value[0].key
    }
  } catch (_) {
    ElMessage.error('加载提示词失败')
  } finally {
    loading.value = false
  }
}

function selectPrompt(key) {
  currentKey.value = key
}

function markDirty(key) {
  const p = prompts.value.find((x) => x.key === key)
  if (!p) return
  const current = p.current_body || p.default_body
  isDirty.value[key] = editState.value[key] !== current
}

async function save(p) {
  const content = editState.value[p.key]
  if (!content?.trim()) {
    ElMessage.warning('内容不能为空')
    return
  }
  savingKey.value = p.key
  try {
    await promptsAPI.update(p.key, content.trim())
    p.current_body = content.trim()
    p.is_customized = true
    isDirty.value[p.key] = false
    ElMessage.success('已保存')
  } catch (_) {
  } finally {
    savingKey.value = null
  }
}

async function reset(p) {
  await ElMessageBox.confirm(`确定将「${p.label}」恢复为系统默认提示词？`, '恢复默认', {
    type: 'warning',
  })
  resettingKey.value = p.key
  try {
    await promptsAPI.reset(p.key)
    p.current_body = null
    p.is_customized = false
    editState.value[p.key] = p.default_body
    isDirty.value[p.key] = false
    ElMessage.success('已恢复默认')
  } catch (_) {
  } finally {
    resettingKey.value = null
  }
}

// 打开版本历史抽屉
async function openHistoryDialog(p) {
  activePromptForModal.value = p
  historyDrawerVisible.value = true
  historyLoading.value = true
  selectedHistoryVersion.value = null
  try {
    const res = await promptsAPI.getTemplateHistory(p.key)
    historyList.value = res.items || res.data || []
  } catch (_) {
    ElMessage.error('获取版本历史失败')
  } finally {
    historyLoading.value = false
  }
}

function previewHistoryVersion(row) {
  selectedHistoryVersion.value = row
}

async function rollbackToVersion(row) {
  const p = activePromptForModal.value
  if (!p) return
  await ElMessageBox.confirm(`确定将提示词「${p.label}」回滚至版本 v${row.version}？`, '版本回滚', {
    type: 'warning',
  })
  try {
    await promptsAPI.rollbackTemplate(p.key, row.version)
    ElMessage.success(`已成功回滚至 v${row.version}`)
    historyDrawerVisible.value = false
    await load()
  } catch (_) {
    ElMessage.error('回滚失败')
  }
}

// 打开执行审计抽屉
async function openRunsDrawer(p) {
  activePromptForModal.value = p
  runsDrawerVisible.value = true
  runsLoading.value = true
  selectedRun.value = null
  try {
    const res = await promptsAPI.listPromptRuns({ prompt_key: p.key, limit: 30 })
    runsList.value = res.items || res.data || []
  } catch (_) {
    ElMessage.error('获取执行审计记录失败')
  } finally {
    runsLoading.value = false
  }
}

function viewRunDetail(row) {
  selectedRun.value = row
}

onMounted(() => load())
</script>

<style scoped>
.prompt-editor-page {
  padding: 0;
  height: 100%;
}
.loading-wrap {
  min-height: 200px;
}

/* 左右布局 */
.editor-layout {
  display: flex;
  height: 100%;
  min-height: calc(100vh - 120px);
}

/* 左侧菜单 */
.left-sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--bg-card, #fff);
  border-right: 1px solid var(--border-color, #e4e4e7);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color, #e4e4e7);
}

.sidebar-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-bright, #18181b);
}

.sidebar-menu {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.menu-item {
  padding: 12px 16px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 4px;
  position: relative;
}

.menu-item:hover {
  background: var(--bg-inner, #f8f8f8);
}

.menu-item.active {
  background: var(--el-color-primary-light-9, #f3e8ff);
}

.menu-item.active .menu-label {
  color: var(--el-color-primary, #7c3aed);
  font-weight: 600;
}

.menu-item-content {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.menu-label {
  font-size: 13px;
  color: var(--text-bright, #18181b);
  flex: 1;
}

.menu-tag {
  font-size: 10px;
  transform: scale(0.9);
}

.dirty-indicator {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 6px;
  height: 6px;
  background: var(--el-color-warning, #f59e0b);
  border-radius: 50%;
}

/* 右侧内容区 */
.right-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

.page-desc {
  margin: 0 0 20px;
  font-size: 13px;
  color: var(--text-muted, #71717a);
  line-height: 1.6;
  padding: 10px 14px;
  background: var(--bg-inner, #f8f8f8);
  border-radius: 8px;
  border-left: 3px solid var(--el-color-primary, #7c3aed);
}

.prompt-card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #e4e4e7);
  border-radius: 12px;
  padding: 20px;
}

.prompt-card-header {
  margin-bottom: 16px;
}

.prompt-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.prompt-label {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-bright, #18181b);
}

.custom-tag {
  font-size: 11px;
}

.prompt-desc {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted, #71717a);
}

.section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted, #71717a);
}

.section-label--locked {
  color: #2563eb;
}

.section-icon {
  font-size: 13px;
}

.prompt-edit-section {
  margin-bottom: 16px;
}

.prompt-textarea :deep(textarea) {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12.5px;
  line-height: 1.6;
}

.prompt-locked-section {
  margin-bottom: 16px;
}

.locked-content {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: #1e40af;
  white-space: pre-wrap;
  line-height: 1.6;
  user-select: none;
}

.prompt-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--border-color, #e4e4e7);
}

.drawer-body {
  padding: 10px 0;
}

.history-preview-box,
.run-detail-box {
  margin-top: 20px;
  padding: 14px;
  background: var(--bg-inner, #f8f8f8);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e4e4e7);
}

.preview-header {
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--text-bright, #18181b);
}

.run-detail-tabs {
  margin-top: 10px;
}
</style>
