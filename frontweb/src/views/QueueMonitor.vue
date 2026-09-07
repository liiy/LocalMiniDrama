<template>
  <div class="queue-monitor">
    <header class="page-header">
      <div class="header-left">
        <el-button class="icon-button" circle title="返回项目列表" @click="router.push('/')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <div>
          <h1>任务中心</h1>
          <div class="runtime-line">
            <span class="health-dot" :class="runtimeHealth" />
            <span>{{ runtimeLabel }}</span>
            <span class="separator">|</span>
            <span>{{ onlineWorkers }} 个 Worker 在线</span>
          </div>
        </div>
      </div>
      <div class="header-actions">
        <el-switch v-model="autoRefresh" active-text="自动刷新" />
        <el-button :loading="recovering" @click="recoverStaleJobs">
          <el-icon><Warning /></el-icon>回收超时任务
        </el-button>
        <el-button type="primary" :loading="loading" @click="refreshAll">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>
    </header>

    <main class="monitor-main">
      <section class="summary-band" aria-label="队列状态汇总">
        <button
          v-for="item in summaryItems"
          :key="item.key"
          type="button"
          class="summary-item"
          :class="[{ active: filters.status === item.key }, `summary-${item.key || 'all'}`]"
          @click="selectStatus(item.key)"
        >
          <span class="summary-label">{{ item.label }}</span>
          <strong>{{ item.count }}</strong>
        </button>
      </section>

      <section class="metrics-band" aria-label="过去二十四小时运行指标">
        <div class="metric-item">
          <span>24 小时吞吐</span>
          <strong>{{ metrics.throughput || 0 }}</strong>
          <small>完成与失败终态</small>
        </div>
        <div class="metric-item">
          <span>成功率</span>
          <strong>{{ formatPercent(metrics.success_rate) }}</strong>
          <small>{{ metrics.completed || 0 }} 成功 / {{ metrics.failed || 0 }} 失败</small>
        </div>
        <div class="metric-item">
          <span>平均执行耗时</span>
          <strong>{{ formatDuration(metrics.avg_duration_seconds) }}</strong>
          <small>P95 {{ formatDuration(metrics.p95_duration_seconds) }}</small>
        </div>
        <div class="metric-item">
          <span>最长积压</span>
          <strong>{{ formatDuration(metrics.oldest_active_seconds) }}</strong>
          <small>{{ metrics.active_count || 0 }} 个活动任务</small>
        </div>
        <el-tag v-if="metrics.sample_truncated" class="sample-warning" type="warning" effect="plain">统计样本已截断</el-tag>
      </section>

      <section class="queue-section">
        <div class="section-toolbar">
          <div class="filters">
            <el-select v-model="filters.queue_name" clearable placeholder="全部队列" class="queue-filter" @change="applyFilters">
              <el-option v-for="queue in queueOptions" :key="queue" :label="queue" :value="queue" />
            </el-select>
            <el-select v-model="filters.status" clearable placeholder="全部状态" class="status-filter" @change="applyFilters">
              <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-input
              v-model="filters.task_type"
              clearable
              placeholder="任务类型"
              class="type-filter"
              @keyup.enter="applyFilters"
              @clear="applyFilters"
            />
            <el-button @click="applyFilters"><el-icon><Search /></el-icon>筛选</el-button>
          </div>
          <span class="result-count">共 {{ total }} 条</span>
        </div>

        <el-table v-loading="loading" :data="jobs" row-key="id" class="jobs-table" empty-text="暂无队列任务">
          <el-table-column label="状态" width="112">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" effect="plain" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="queue_name" label="队列" width="105" />
          <el-table-column prop="task_type" label="任务类型" min-width="210" show-overflow-tooltip />
          <el-table-column label="任务 ID" min-width="155">
            <template #default="{ row }"><code>{{ shortId(row.id) }}</code></template>
          </el-table-column>
          <el-table-column label="尝试" width="78" align="center">
            <template #default="{ row }">{{ row.attempts || 0 }}/{{ row.max_attempts || 0 }}</template>
          </el-table-column>
          <el-table-column prop="locked_by" label="执行 Worker" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.locked_by || '-' }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="172">
            <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="错误" min-width="180" show-overflow-tooltip>
            <template #default="{ row }"><span class="error-text">{{ row.error || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="154" fixed="right">
            <template #default="{ row }">
              <el-button link title="查看详情" @click="openDetail(row)"><el-icon><View /></el-icon></el-button>
              <el-button
                v-if="canRetry(row)"
                link
                type="primary"
                title="重新入队"
                :loading="actingJobId === row.id"
                @click="retryJob(row)"
              ><el-icon><RefreshRight /></el-icon></el-button>
              <el-button
                v-if="canCancel(row)"
                link
                type="danger"
                title="取消任务"
                :loading="actingJobId === row.id"
                @click="cancelJob(row)"
              ><el-icon><Close /></el-icon></el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-row">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :page-sizes="[20, 50, 100]"
            :total="total"
            layout="total, sizes, prev, pager, next"
            @current-change="loadJobs"
            @size-change="handlePageSizeChange"
          />
        </div>
      </section>

      <section v-if="metrics.failure_hotspots?.length" class="failure-section">
        <div class="section-heading">
          <div>
            <h2>失败热点</h2>
            <span>过去 24 小时按任务类型聚合</span>
          </div>
        </div>
        <el-table :data="metrics.failure_hotspots" class="failure-table" empty-text="暂无失败记录">
          <el-table-column prop="task_type" label="任务类型" min-width="240" />
          <el-table-column prop="count" label="失败次数" width="105" align="center" />
          <el-table-column prop="latest_error" label="最近错误" min-width="360" show-overflow-tooltip>
            <template #default="{ row }"><span class="error-text">{{ row.latest_error || '-' }}</span></template>
          </el-table-column>
        </el-table>
      </section>

      <section class="workers-section">
        <div class="section-heading">
          <div>
            <h2>Worker 节点</h2>
            <span>最近心跳与负责队列</span>
          </div>
          <el-tag :type="runtimeTagType" effect="plain">内嵌 Runtime：{{ runtimeLabel }}</el-tag>
        </div>
        <el-table :data="workers" row-key="worker_id" class="workers-table" empty-text="暂无 Worker 注册记录">
          <el-table-column label="状态" width="105">
            <template #default="{ row }"><el-tag :type="workerStatusType(row.status)" effect="plain" size="small">{{ workerStatusLabel(row.status) }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="worker_id" label="Worker ID" min-width="220" show-overflow-tooltip />
          <el-table-column prop="hostname" label="主机" min-width="150" />
          <el-table-column prop="process_id" label="PID" width="90" />
          <el-table-column label="队列" min-width="260">
            <template #default="{ row }">
              <div class="queue-tags"><el-tag v-for="queue in row.queues || []" :key="queue" size="small" effect="plain">{{ queue }}</el-tag></div>
            </template>
          </el-table-column>
          <el-table-column label="最后心跳" width="180">
            <template #default="{ row }">{{ formatTime(row.heartbeat_at) }}</template>
          </el-table-column>
        </el-table>
      </section>
    </main>

    <el-drawer v-model="detailVisible" title="任务详情" size="min(680px, 92vw)" destroy-on-close>
      <div v-loading="detailLoading" class="detail-body">
        <el-descriptions v-if="selectedJob" :column="2" border>
          <el-descriptions-item label="任务 ID" :span="2"><code>{{ selectedJob.id }}</code></el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusLabel(selectedJob.status) }}</el-descriptions-item>
          <el-descriptions-item label="队列">{{ selectedJob.queue_name }}</el-descriptions-item>
          <el-descriptions-item label="任务类型" :span="2">{{ selectedJob.task_type }}</el-descriptions-item>
          <el-descriptions-item label="Async Task">{{ selectedJob.async_task_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Workflow">{{ selectedJob.workflow_run_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(selectedJob.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(selectedJob.completed_at) }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="selectedJob?.error" class="detail-block error-block">
          <h3>错误信息</h3><pre>{{ selectedJob.error }}</pre>
        </div>
        <div class="detail-block"><h3>任务载荷</h3><pre>{{ formatJson(selectedJob?.payload) }}</pre></div>
        <div class="detail-block"><h3>执行结果</h3><pre>{{ formatJson(selectedJob?.result) }}</pre></div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Close, Refresh, RefreshRight, Search, View, Warning } from '@element-plus/icons-vue'
import { queueAPI } from '@/api/workflows'

const router = useRouter()
const loading = ref(false)
const recovering = ref(false)
const actingJobId = ref('')
const jobs = ref([])
const workers = ref([])
const runtime = ref({})
const metrics = ref({})
const total = ref(0)
const summary = ref({})
const page = ref(1)
const pageSize = ref(20)
const autoRefresh = ref(true)
const detailVisible = ref(false)
const detailLoading = ref(false)
const selectedJob = ref(null)
let refreshTimer = null

const filters = reactive({ queue_name: '', status: '', task_type: '' })
const queueOptions = ['workflow', 'stories', 'entities', 'storyboards', 'images', 'videos', 'audio']
const statusOptions = [
  { value: 'pending', label: '等待中' },
  { value: 'retry', label: '待重试' },
  { value: 'processing', label: '执行中' },
  { value: 'waiting_child', label: '等待子任务' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const summaryItems = computed(() => [
  { key: '', label: '全部', count: summary.value.total || 0 },
  ...statusOptions.map(item => ({ key: item.value, label: item.label, count: summary.value[item.value] || 0 })),
])
const onlineWorkers = computed(() => workers.value.filter(item => item.status === 'online').length)
const runtimeLabel = computed(() => {
  const status = runtime.value?.status || 'unknown'
  return { running: '运行中', disabled: '未启用', stopped: '已停止', stopping: '停止中', created: '待启动' }[status] || '未知'
})
const runtimeHealth = computed(() => runtime.value?.status === 'running' ? 'healthy' : runtime.value?.status === 'disabled' ? 'disabled' : 'warning')
const runtimeTagType = computed(() => runtime.value?.status === 'running' ? 'success' : runtime.value?.status === 'disabled' ? 'info' : 'warning')

function requestParams() {
  return {
    queue_name: filters.queue_name || undefined,
    status: filters.status || undefined,
    task_type: filters.task_type.trim() || undefined,
    limit: pageSize.value,
    offset: (page.value - 1) * pageSize.value,
  }
}

async function loadJobs(silent = false) {
  if (!silent) loading.value = true
  try {
    const data = await queueAPI.listJobs(requestParams())
    jobs.value = data?.items || []
    total.value = Number(data?.total || 0)
    summary.value = data?.summary || {}
    const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value))
    if (page.value > maxPage) {
      page.value = maxPage
      return loadJobs(true)
    }
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadHealth() {
  const [workerData, runtimeData] = await Promise.all([queueAPI.listWorkers({ limit: 100 }), queueAPI.getRuntimeStatus()])
  workers.value = Array.isArray(workerData) ? workerData : []
  runtime.value = runtimeData || {}
}

async function loadMetrics() {
  // 状态筛选只控制任务明细，运行质量始终按当前队列和任务类型的完整终态计算。
  metrics.value = await queueAPI.getMetrics({
    hours: 24,
    queue_name: filters.queue_name || undefined,
    task_type: filters.task_type.trim() || undefined,
  }) || {}
}

async function refreshAll(silent = false) {
  try {
    await Promise.all([loadJobs(silent), loadHealth(), loadMetrics()])
  } catch (error) {
    if (!silent) ElMessage.error(error.message || '任务中心刷新失败')
  }
}

function applyFilters() {
  page.value = 1
  Promise.all([loadJobs(), loadMetrics()]).catch(() => {})
}

function selectStatus(status) {
  filters.status = status
  applyFilters()
}

function handlePageSizeChange() {
  page.value = 1
  loadJobs()
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  selectedJob.value = row
  try {
    selectedJob.value = await queueAPI.getJob(row.id)
  } finally {
    detailLoading.value = false
  }
}

function canRetry(row) {
  return ['failed', 'cancelled'].includes(row.status)
}

function canCancel(row) {
  return ['pending', 'retry', 'processing', 'waiting_child'].includes(row.status)
}

async function retryJob(row) {
  actingJobId.value = row.id
  try {
    await queueAPI.retryJob(row.id)
    ElMessage.success('任务已重新入队')
    await loadJobs(true)
  } finally {
    actingJobId.value = ''
  }
}

async function cancelJob(row) {
  try {
    await ElMessageBox.confirm('取消后，已发出的外部 AI 请求可能仍会完成，但结果不会继续推进工作流。', '取消任务', {
      confirmButtonText: '确认取消', cancelButtonText: '返回', type: 'warning',
    })
  } catch {
    return
  }
  actingJobId.value = row.id
  try {
    await queueAPI.cancelJob(row.id, '由任务中心人工取消')
    ElMessage.success('任务已取消')
    await loadJobs(true)
  } finally {
    actingJobId.value = ''
  }
}

async function recoverStaleJobs() {
  try {
    await ElMessageBox.confirm('将失联 Worker 标记为异常，并回收执行超时的任务。', '回收超时任务', {
      confirmButtonText: '开始回收', cancelButtonText: '取消', type: 'warning',
    })
  } catch {
    return
  }
  recovering.value = true
  try {
    const result = await queueAPI.recoverStale({ stale_worker_seconds: 90, stale_job_seconds: 1800, limit: 100 })
    const count = result?.stale_jobs?.count || 0
    ElMessage.success(`回收完成，共处理 ${count} 个超时任务`)
    await refreshAll(true)
  } finally {
    recovering.value = false
  }
}

function statusLabel(status) {
  return Object.fromEntries(statusOptions.map(item => [item.value, item.label]))[status] || status || '未知'
}

function statusType(status) {
  return { processing: 'primary', waiting_child: 'warning', retry: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }[status] || 'info'
}

function workerStatusLabel(status) {
  return { online: '在线', offline: '离线', stale: '心跳超时' }[status] || status || '未知'
}

function workerStatusType(status) {
  return { online: 'success', stale: 'danger', offline: 'info' }[status] || 'info'
}

function shortId(value) {
  const text = String(value || '')
  return text.length > 18 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function formatJson(value) {
  if (value == null || (typeof value === 'object' && Object.keys(value).length === 0)) return '-'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function formatPercent(value) {
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(number % 1 ? 1 : 0)}%` : '-'
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds < 60) return `${Math.round(seconds)}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${Math.round(seconds % 60)}秒`
  return `${Math.floor(seconds / 3600)}时${Math.round((seconds % 3600) / 60)}分`
}

function scheduleRefresh() {
  clearInterval(refreshTimer)
  refreshTimer = null
  if (autoRefresh.value) refreshTimer = setInterval(() => refreshAll(true), 5000)
}

watch(autoRefresh, scheduleRefresh)
onMounted(() => {
  refreshAll()
  scheduleRefresh()
})
onBeforeUnmount(() => clearInterval(refreshTimer))
</script>

<style scoped>
.queue-monitor { min-height: 100vh; background: #111315; color: #e5e7eb; }
.page-header { min-height: 76px; padding: 14px 24px; border-bottom: 1px solid #2a2e33; background: #17191c; display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.header-left, .header-actions, .runtime-line, .filters, .section-heading, .queue-tags { display: flex; align-items: center; }
.header-left { gap: 14px; min-width: 0; }
.header-actions { gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.page-header h1 { margin: 0 0 5px; font-size: 22px; line-height: 1.15; letter-spacing: 0; }
.runtime-line { gap: 7px; color: #9ca3af; font-size: 13px; }
.separator { color: #4b5563; }
.health-dot { width: 8px; height: 8px; border-radius: 50%; background: #f59e0b; }
.health-dot.healthy { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, .13); }
.health-dot.disabled { background: #6b7280; }
.icon-button { flex: 0 0 auto; }
.monitor-main { padding: 20px 24px 34px; max-width: 1680px; margin: 0 auto; }
.summary-band { display: grid; grid-template-columns: repeat(8, minmax(95px, 1fr)); border: 1px solid #2a2e33; border-radius: 6px; overflow: hidden; background: #17191c; margin-bottom: 16px; }
.summary-item { min-height: 72px; padding: 11px 14px; border: 0; border-right: 1px solid #2a2e33; color: #9ca3af; background: transparent; text-align: left; cursor: pointer; }
.summary-item:last-child { border-right: 0; }
.summary-item:hover, .summary-item.active { background: #22262a; }
.summary-item.active { box-shadow: inset 0 -3px #22c55e; }
.summary-label { display: block; font-size: 12px; }
.summary-item strong { display: block; margin-top: 5px; color: #f3f4f6; font-size: 24px; line-height: 1; letter-spacing: 0; }
.summary-failed strong { color: #f87171; }
.summary-processing strong { color: #60a5fa; }
.summary-retry strong, .summary-waiting_child strong { color: #fbbf24; }
.summary-completed strong { color: #4ade80; }
.metrics-band { position: relative; display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); margin-bottom: 22px; border-top: 1px solid #30343a; border-bottom: 1px solid #30343a; background: #17191c; }
.metric-item { min-height: 92px; padding: 14px 18px; border-right: 1px solid #2a2e33; }
.metric-item:last-of-type { border-right: 0; }
.metric-item span, .metric-item small { display: block; color: #9ca3af; font-size: 12px; }
.metric-item strong { display: block; margin: 6px 0; color: #f3f4f6; font-size: 22px; line-height: 1; letter-spacing: 0; }
.sample-warning { position: absolute; top: 8px; right: 8px; }
.queue-section, .workers-section, .failure-section { border-top: 1px solid #30343a; background: #17191c; }
.queue-section { margin-bottom: 24px; }
.failure-section { margin-bottom: 24px; }
.section-toolbar { min-height: 62px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid #2a2e33; }
.filters { gap: 8px; flex-wrap: wrap; }
.queue-filter { width: 140px; }
.status-filter { width: 140px; }
.type-filter { width: 260px; }
.result-count { color: #9ca3af; font-size: 13px; white-space: nowrap; }
.jobs-table, .workers-table { width: 100%; }
.error-text { color: #fca5a5; }
code { color: #a7f3d0; font-family: Consolas, 'Courier New', monospace; font-size: 12px; }
.pagination-row { min-height: 58px; display: flex; justify-content: flex-end; align-items: center; padding: 8px 14px; border-top: 1px solid #2a2e33; }
.section-heading { min-height: 62px; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid #2a2e33; }
.section-heading h2 { margin: 0 0 3px; font-size: 16px; letter-spacing: 0; }
.section-heading span { color: #9ca3af; font-size: 12px; }
.queue-tags { gap: 5px; flex-wrap: wrap; }
.detail-body { min-height: 220px; }
.detail-block { margin-top: 18px; }
.detail-block h3 { margin: 0 0 8px; font-size: 14px; letter-spacing: 0; }
.detail-block pre { margin: 0; padding: 12px; max-height: 320px; overflow: auto; border: 1px solid #30343a; border-radius: 4px; background: #111315; color: #d1d5db; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.6 Consolas, 'Courier New', monospace; }
.error-block pre { border-color: rgba(239, 68, 68, .38); color: #fca5a5; }
:deep(.el-table) { --el-table-bg-color: #17191c; --el-table-tr-bg-color: #17191c; --el-table-header-bg-color: #1d2024; --el-table-row-hover-bg-color: #22262a; --el-table-border-color: #2a2e33; --el-table-text-color: #d1d5db; --el-table-header-text-color: #9ca3af; }

:global(html.light) .queue-monitor { background: #f5f7f8; color: #1f2937; }
:global(html.light) .page-header, :global(html.light) .summary-band, :global(html.light) .metrics-band, :global(html.light) .queue-section, :global(html.light) .failure-section, :global(html.light) .workers-section { background: #fff; border-color: #dfe3e8; }
:global(html.light) .metric-item { border-color: #e5e7eb; }
:global(html.light) .metric-item strong { color: #111827; }
:global(html.light) .summary-item { border-color: #e5e7eb; color: #6b7280; }
:global(html.light) .summary-item:hover, :global(html.light) .summary-item.active { background: #f3f6f5; }
:global(html.light) .summary-item strong { color: #111827; }
:global(html.light) .detail-block pre { background: #f7f8fa; color: #374151; border-color: #dfe3e8; }
:global(html.light) .queue-monitor :deep(.el-table) { --el-table-bg-color: #fff; --el-table-tr-bg-color: #fff; --el-table-header-bg-color: #f5f7f8; --el-table-row-hover-bg-color: #f3f6f5; --el-table-border-color: #e5e7eb; --el-table-text-color: #374151; --el-table-header-text-color: #6b7280; }

@media (max-width: 1080px) {
  .summary-band { grid-template-columns: repeat(4, minmax(95px, 1fr)); }
  .summary-item:nth-child(4) { border-right: 0; }
  .summary-item:nth-child(-n + 4) { border-bottom: 1px solid #2a2e33; }
  .metrics-band { grid-template-columns: repeat(2, minmax(150px, 1fr)); }
  .metric-item:nth-child(-n + 2) { border-bottom: 1px solid #2a2e33; }
  .metric-item:nth-child(even) { border-right: 0; }
}
@media (max-width: 720px) {
  .page-header { align-items: flex-start; padding: 12px; flex-direction: column; }
  .header-actions { width: 100%; justify-content: flex-start; }
  .monitor-main { padding: 12px; }
  .summary-band { grid-template-columns: repeat(2, minmax(90px, 1fr)); }
  .summary-item { border-bottom: 1px solid #2a2e33; }
  .summary-item:nth-child(even) { border-right: 0; }
  .metrics-band { grid-template-columns: 1fr; }
  .metric-item { border-right: 0; border-bottom: 1px solid #2a2e33; }
  .metric-item:last-of-type { border-bottom: 0; }
  .section-toolbar { align-items: flex-start; flex-direction: column; }
  .filters { width: 100%; }
  .queue-filter, .status-filter, .type-filter { width: 100%; }
  .pagination-row { justify-content: flex-start; overflow-x: auto; }
}
</style>
