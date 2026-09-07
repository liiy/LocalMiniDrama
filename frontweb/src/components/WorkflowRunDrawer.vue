<template>
  <el-drawer
    v-model="visible"
    title="制作工作流"
    size="min(680px, 96vw)"
    destroy-on-close
    class="workflow-run-drawer"
    @closed="stopPolling"
  >
    <div class="workflow-toolbar">
      <el-select
        v-model="selectedRunId"
        placeholder="选择工作流"
        class="workflow-selector"
        :loading="listLoading"
        @change="loadExecutionState"
      >
        <el-option
          v-for="run in workflowRuns"
          :key="run.id"
          :label="`${workflowTypeLabel(run.type)} · ${statusLabel(run.status)}`"
          :value="run.id"
        />
      </el-select>
      <el-dropdown trigger="click" @command="createWorkflow">
        <el-button type="primary" plain :icon="Plus" :loading="actionLoading === 'create'">
          新建
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="original_script">原创剧本流程</el-dropdown-item>
            <el-dropdown-item command="novel_adaptation">小说改编流程</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button circle :icon="Refresh" title="刷新工作流" :loading="detailLoading" @click="refreshAll" />
    </div>

    <el-empty v-if="!listLoading && workflowRuns.length === 0" description="当前项目暂无工作流" />

    <template v-else-if="workflowState?.workflow">
      <div class="workflow-summary">
        <div class="workflow-summary-main">
          <div class="workflow-name">{{ workflowTypeLabel(workflowState.workflow.type) }}</div>
          <el-tag :type="statusTagType(workflowState.workflow.status)" effect="plain">
            {{ statusLabel(workflowState.workflow.status) }}
          </el-tag>
        </div>
        <el-progress
          :percentage="Number(workflowState.progress?.percent || 0)"
          :status="progressStatus"
          :stroke-width="8"
        />
        <div class="workflow-counts">
          <span>完成 {{ workflowState.progress?.completed || 0 }}/{{ workflowState.progress?.total || 0 }}</span>
          <span v-if="workflowState.progress?.failed">失败 {{ workflowState.progress.failed }}</span>
          <span v-if="workflowState.progress?.runnable">就绪 {{ workflowState.progress.runnable }}</span>
          <span v-if="workflowState.progress?.waiting">等待 {{ workflowState.progress.waiting }}</span>
        </div>
      </div>

      <div class="workflow-actions">
        <el-button
          v-if="canExecute"
          type="primary"
          :icon="VideoPlay"
          :loading="actionLoading === 'execute'"
          @click="executeUntilBlocked"
        >
          执行就绪步骤
        </el-button>
        <el-button
          v-if="canPause"
          :icon="VideoPause"
          :loading="actionLoading === 'pause'"
          @click="pauseWorkflow"
        >
          暂停
        </el-button>
        <el-button
          v-if="canResume"
          type="primary"
          plain
          :icon="RefreshRight"
          :loading="actionLoading === 'resume'"
          @click="resumeWorkflow"
        >
          恢复
        </el-button>
        <el-button
          v-if="canCancel"
          type="danger"
          plain
          :icon="Close"
          :loading="actionLoading === 'cancel'"
          @click="cancelWorkflow"
        >
          取消
        </el-button>
      </div>

      <div v-loading="detailLoading" class="workflow-steps">
        <div
          v-for="(step, index) in workflowState.steps || []"
          :key="step.id || step.step_key"
          class="workflow-step"
          :class="`is-${step.status}`"
        >
          <div class="step-index">{{ index + 1 }}</div>
          <div class="step-content">
            <div class="step-heading">
              <span class="step-title">{{ step.input_payload?.title || step.step_key }}</span>
              <el-tag size="small" :type="statusTagType(step.status)" effect="plain">
                {{ statusLabel(step.status) }}
              </el-tag>
            </div>
            <div class="step-meta">
              <span v-if="step.agent_name">Agent: {{ step.agent_name }}</span>
              <span v-if="step.skill_key">Skill: {{ step.skill_key }}</span>
              <span v-if="step.retry_count">重试 {{ step.retry_count }} 次</span>
            </div>
            <div v-if="step.depends_on?.length" class="step-dependencies">
              依赖：{{ step.depends_on.map(stepTitle).join('、') }}
            </div>
            <el-alert v-if="step.error" :title="step.error" type="error" :closable="false" show-icon />
            <div v-if="step.status === 'failed'" class="step-actions">
              <el-button
                size="small"
                type="warning"
                plain
                :icon="RefreshRight"
                :loading="actionLoading === `retry:${step.step_key}`"
                @click="retryStep(step)"
              >
                重试
              </el-button>
            </div>
            <div v-if="isWaitingApproval(step)" class="step-actions">
              <el-button
                size="small"
                type="success"
                :icon="Check"
                :loading="actionLoading === `approve:${step.step_key}`"
                @click="approveStep(step)"
              >
                审核通过
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :icon="Close"
                :loading="actionLoading === `reject:${step.step_key}`"
                @click="rejectStep(step)"
              >
                驳回重做
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close, Plus, Refresh, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { workflowAPI } from '@/api/workflows'

const props = defineProps({
  dramaId: {
    type: [Number, String],
    default: null,
  },
})

const visible = ref(false)
const workflowRuns = ref([])
const selectedRunId = ref('')
const workflowState = ref(null)
const listLoading = ref(false)
const detailLoading = ref(false)
const actionLoading = ref('')
let pollingTimer = null

const terminalStatuses = new Set(['completed', 'failed', 'cancelled'])
const currentStatus = computed(() => workflowState.value?.workflow?.status || '')
const canExecute = computed(() => ['pending', 'processing'].includes(currentStatus.value))
const canPause = computed(() => ['pending', 'processing', 'waiting_approval'].includes(currentStatus.value))
const canResume = computed(() => currentStatus.value === 'paused')
const canCancel = computed(() => currentStatus.value && !terminalStatuses.has(currentStatus.value))
const progressStatus = computed(() => {
  if (currentStatus.value === 'completed') return 'success'
  if (['failed', 'cancelled'].includes(currentStatus.value)) return 'exception'
  return undefined
})

const workflowTypeLabels = {
  original_script: '原创剧本全流程',
  novel_adaptation: '小说改编全流程',
  entity_extraction: '角色场景道具提取',
  storyboard_generation: '分镜制作',
  asset_generation: '视觉资产生成',
  voice_music_generation: '声音与音乐设计',
  video_production: '视频制作',
}

const statusLabels = {
  pending: '待执行',
  processing: '执行中',
  waiting_child: '等待子任务',
  waiting_approval: '等待审核',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  retry: '等待重试',
  skipped: '已跳过',
}

function workflowTypeLabel(type) {
  return workflowTypeLabels[type] || type || '工作流'
}

function statusLabel(status) {
  return statusLabels[status] || status || '未知'
}

function statusTagType(status) {
  if (status === 'completed') return 'success'
  if (['failed', 'cancelled'].includes(status)) return 'danger'
  if (['waiting_approval', 'retry'].includes(status)) return 'warning'
  if (['processing', 'waiting_child'].includes(status)) return 'primary'
  return 'info'
}

function stepTitle(stepKey) {
  const step = workflowState.value?.steps?.find((item) => item.step_key === stepKey)
  return step?.input_payload?.title || stepKey
}

function isWaitingApproval(step) {
  return ['waiting_approval', 'awaiting_approval', 'approval_required'].includes(step.status)
}

async function loadWorkflowRuns({ keepSelection = true } = {}) {
  if (!props.dramaId) return
  listLoading.value = true
  try {
    const runs = await workflowAPI.list({ drama_id: props.dramaId, limit: 50 })
    workflowRuns.value = Array.isArray(runs) ? runs : []
    const selectionStillExists = workflowRuns.value.some((run) => run.id === selectedRunId.value)
    if (!keepSelection || !selectionStillExists) selectedRunId.value = workflowRuns.value[0]?.id || ''
  } finally {
    listLoading.value = false
  }
}

async function loadExecutionState({ quiet = false } = {}) {
  if (!selectedRunId.value) {
    workflowState.value = null
    return
  }
  if (!quiet) detailLoading.value = true
  try {
    workflowState.value = await workflowAPI.getGraph(selectedRunId.value)
  } finally {
    if (!quiet) detailLoading.value = false
  }
}

async function refreshAll() {
  await loadWorkflowRuns()
  await loadExecutionState()
}

async function createWorkflow(type) {
  const isNovel = type === 'novel_adaptation'
  let input
  try {
    input = await ElMessageBox.prompt(
      isNovel ? '请输入小说名称或改编要求' : '请输入核心主题、类型与创作要求',
      isNovel ? '新建小说改编流程' : '新建原创剧本流程',
      {
        inputType: 'textarea',
        inputPlaceholder: isNovel ? '小说名称、章节范围、改编方向' : '题材、核心冲突、目标集数、受众',
        inputValidator: (value) => Boolean(value?.trim()) || '请输入创作要求',
        confirmButtonText: '创建',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  actionLoading.value = 'create'
  try {
    const payload = {
      drama_id: Number(props.dramaId),
      user_request: input.value.trim(),
    }
    const created = isNovel
      ? await workflowAPI.createNovelAdaptation({
          ...payload,
          novel_title: input.value.trim(),
          adaptation_requirements: input.value.trim(),
        })
      : await workflowAPI.createOriginalScript({
          ...payload,
          core_theme: input.value.trim(),
        })
    await loadWorkflowRuns({ keepSelection: false })
    selectedRunId.value = created.id
    await loadExecutionState()
    ElMessage.success('工作流已创建')
  } finally {
    actionLoading.value = ''
  }
}

async function runAction(key, action, successMessage) {
  actionLoading.value = key
  try {
    await action()
    if (successMessage) ElMessage.success(successMessage)
    await refreshAll()
  } finally {
    actionLoading.value = ''
  }
}

function executeUntilBlocked() {
  return runAction(
    'execute',
    () => workflowAPI.executeUntilBlocked(selectedRunId.value, {
      queue: true,
      execution_mode: 'queued',
      execute_ai: true,
    }),
    '已提交就绪步骤',
  )
}

function pauseWorkflow() {
  return runAction('pause', () => workflowAPI.pause(selectedRunId.value), '工作流已暂停')
}

function resumeWorkflow() {
  return runAction('resume', () => workflowAPI.resume(selectedRunId.value), '工作流已恢复')
}

async function cancelWorkflow() {
  try {
    await ElMessageBox.confirm('取消后未执行步骤将不再继续，是否确认？', '取消工作流', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '返回',
    })
  } catch {
    return
  }
  return runAction('cancel', () => workflowAPI.cancel(selectedRunId.value, '用户在制作工作台取消'), '工作流已取消')
}

function retryStep(step) {
  return runAction(
    `retry:${step.step_key}`,
    () => workflowAPI.retryStep(selectedRunId.value, step.step_key),
    '步骤已重置为待执行',
  )
}

async function approveStep(step) {
  let value = ''
  try {
    const input = await ElMessageBox.prompt('可填写本次审核意见', '审核通过', {
      inputType: 'textarea',
      inputPlaceholder: '审核意见（选填）',
      confirmButtonText: '通过',
      cancelButtonText: '返回',
    })
    value = input.value || ''
  } catch {
    return
  }
  return runAction(
    `approve:${step.step_key}`,
    () => workflowAPI.approveStep(selectedRunId.value, step.step_key, {
      approver: 'user',
      feedback: value,
      auto_resume: false,
    }),
    '审核已通过',
  )
}

async function rejectStep(step) {
  let value = ''
  try {
    const input = await ElMessageBox.prompt('请填写需要修改的内容', '驳回重做', {
      inputType: 'textarea',
      inputPlaceholder: '修改意见',
      inputValidator: (text) => Boolean(text?.trim()) || '请填写修改意见',
      confirmButtonText: '驳回',
      cancelButtonText: '返回',
    })
    value = input.value || ''
  } catch {
    return
  }
  return runAction(
    `reject:${step.step_key}`,
    () => workflowAPI.rejectStep(selectedRunId.value, step.step_key, {
      rejector: 'user',
      reason: value.trim(),
      action: 'retry',
    }),
    '步骤已驳回并等待重做',
  )
}

function startPolling() {
  stopPolling()
  // 使用普通鉴权请求轮询，避免原生 EventSource 无法携带 Authorization 请求头。
  pollingTimer = window.setInterval(async () => {
    if (!visible.value || !selectedRunId.value || detailLoading.value || actionLoading.value) return
    try {
      await loadExecutionState({ quiet: true })
    } catch {
      // request 拦截器已展示错误；轮询失败不关闭抽屉，便于服务恢复后自动更新。
    }
  }, 3000)
}

function stopPolling() {
  if (pollingTimer) window.clearInterval(pollingTimer)
  pollingTimer = null
}

async function open() {
  visible.value = true
  await loadWorkflowRuns({ keepSelection: false })
  await loadExecutionState()
  startPolling()
}

onBeforeUnmount(stopPolling)

defineExpose({ open, refresh: refreshAll })
</script>

<style scoped>
.workflow-toolbar,
.workflow-summary-main,
.workflow-actions,
.workflow-counts,
.step-heading,
.step-meta,
.step-actions {
  display: flex;
  align-items: center;
}

.workflow-toolbar {
  gap: 8px;
  margin-bottom: 16px;
}

.workflow-selector {
  flex: 1;
  min-width: 0;
}

.workflow-summary {
  padding: 14px 0 16px;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.workflow-summary-main {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.workflow-name {
  min-width: 0;
  color: var(--el-text-color-primary);
  font-size: 16px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.workflow-counts {
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.workflow-actions {
  flex-wrap: wrap;
  gap: 8px;
  padding: 14px 0;
}

.workflow-actions :deep(.el-button + .el-button),
.step-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.workflow-steps {
  min-height: 120px;
}

.workflow-step {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  padding: 12px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.step-index {
  display: flex;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--el-border-color);
  border-radius: 50%;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.is-completed .step-index {
  border-color: var(--el-color-success);
  color: var(--el-color-success);
}

.is-failed .step-index,
.is-cancelled .step-index {
  border-color: var(--el-color-danger);
  color: var(--el-color-danger);
}

.is-processing .step-index,
.is-waiting_child .step-index {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.step-content {
  min-width: 0;
}

.step-heading {
  justify-content: space-between;
  gap: 10px;
}

.step-title {
  min-width: 0;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.step-meta {
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 5px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.step-dependencies {
  margin-top: 5px;
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.workflow-step :deep(.el-alert) {
  margin-top: 8px;
}

.step-actions {
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 9px;
}

@media (max-width: 520px) {
  .step-heading {
    align-items: flex-start;
  }

  .workflow-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 8px);
  }
}
</style>
