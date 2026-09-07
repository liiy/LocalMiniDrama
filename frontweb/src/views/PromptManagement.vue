<template>
  <main class="prompt-console">
    <header class="page-header">
      <el-button circle title="返回项目列表" @click="$router.push('/')"><el-icon><ArrowLeft /></el-icon></el-button>
      <div><h1>Prompt 管理与成本</h1><p>统一版本、运行证据与模型消耗</p></div>
      <el-button :loading="loading" title="刷新数据" @click="loadAll"><el-icon><Refresh /></el-icon></el-button>
    </header>

    <section class="metrics-band">
      <div><span>调用次数</span><strong>{{ metrics.total_calls || 0 }}</strong></div>
      <div><span>Token 总量</span><strong>{{ number(metrics.total_tokens) }}</strong></div>
      <div><span>累计成本</span><strong>${{ money(metrics.total_cost) }}</strong></div>
      <div><span>平均延迟</span><strong>{{ number(metrics.avg_latency_ms) }} ms</strong></div>
    </section>

    <el-tabs v-model="activeTab" class="content-tabs">
      <el-tab-pane label="平台 Prompt" name="registry">
        <section class="toolbar">
          <el-input v-model="keyword" clearable placeholder="按 Prompt Key 筛选" />
          <el-select v-model="status" clearable placeholder="全部状态">
            <el-option label="已激活" value="active" /><el-option label="草稿" value="draft" /><el-option label="已废弃" value="deprecated" />
          </el-select>
        </section>
        <el-table v-loading="loading" :data="filteredTemplates" empty-text="暂无 Prompt 模板">
          <el-table-column prop="prompt_key" label="Prompt Key" min-width="220" />
          <el-table-column prop="agent_name" label="Agent" width="150" />
          <el-table-column prop="skill_key" label="Skill" min-width="190" />
          <el-table-column prop="version" label="版本" width="80"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openVersions(row)">版本对比</el-button>
              <el-button link @click="openRuns(row)">运行记录</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="系统提示词" name="legacy"><PromptEditor /></el-tab-pane>
      <el-tab-pane label="成本明细" name="cost">
        <el-table :data="metrics.cost_breakdown || []" empty-text="暂无成本记录">
          <el-table-column prop="model" label="模型" min-width="180" />
          <el-table-column prop="agent_name" label="Agent" min-width="160" />
          <el-table-column prop="calls" label="调用" width="100" />
          <el-table-column prop="total_tokens" label="Token" width="140"><template #default="{ row }">{{ number(row.total_tokens) }}</template></el-table-column>
          <el-table-column prop="total_cost" label="成本（USD）" width="140"><template #default="{ row }">${{ money(row.total_cost) }}</template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="versionVisible" title="版本对比与回滚" size="720px">
      <div class="version-picker">
        <el-select v-model="versionA" placeholder="版本 A"><el-option v-for="v in histories" :key="`a${v.id}`" :label="`v${v.version}`" :value="v.version" /></el-select>
        <el-select v-model="versionB" placeholder="版本 B"><el-option v-for="v in histories" :key="`b${v.id}`" :label="`v${v.version}`" :value="v.version" /></el-select>
        <el-button type="primary" :disabled="!versionA || !versionB" @click="compareVersions">对比</el-button>
      </div>
      <el-alert v-if="comparison" :title="comparison.is_template_identical ? '两个版本正文一致' : '两个版本正文存在差异'" :type="comparison.is_template_identical ? 'success' : 'warning'" show-icon />
      <div v-if="comparison" class="compare-grid">
        <div><strong>v{{ versionA }}</strong><pre>{{ comparison.version_a?.template }}</pre></div>
        <div><strong>v{{ versionB }}</strong><pre>{{ comparison.version_b?.template }}</pre></div>
      </div>
      <el-table :data="histories">
        <el-table-column prop="version" label="版本" width="90"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-button v-if="row.status !== 'active'" link type="warning" @click="rollback(row)">回滚</el-button></template></el-table-column>
      </el-table>
    </el-drawer>

    <el-drawer v-model="runsVisible" title="Prompt 运行记录" size="680px">
      <el-table :data="runs"><el-table-column prop="id" label="ID" width="80" /><el-table-column prop="model" label="模型" /><el-table-column prop="status" label="状态" width="130" /><el-table-column prop="cost" label="成本" width="100" /><el-table-column prop="created_at" label="时间" min-width="180" /></el-table>
    </el-drawer>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PromptEditor from '@/components/PromptEditor.vue'
import { promptsAPI } from '@/api/prompts'

const loading = ref(false)
const activeTab = ref('registry')
const templates = ref([])
const metrics = ref({})
const keyword = ref('')
const status = ref('')
const versionVisible = ref(false)
const runsVisible = ref(false)
const activePrompt = ref(null)
const histories = ref([])
const runs = ref([])
const versionA = ref(null)
const versionB = ref(null)
const comparison = ref(null)

// Registry 返回全部版本；列表默认保留每个 prompt_key 的最新版本，减少重复信息。
const filteredTemplates = computed(() => {
  const latest = new Map()
  for (const item of templates.value) if (!latest.has(item.prompt_key)) latest.set(item.prompt_key, item)
  return [...latest.values()].filter((item) => (!keyword.value || item.prompt_key.toLowerCase().includes(keyword.value.toLowerCase())) && (!status.value || item.status === status.value))
})

const number = (value) => Number(value || 0).toLocaleString('zh-CN')
const money = (value) => Number(value || 0).toFixed(6)

async function loadAll() {
  loading.value = true
  try {
    const [list, observability] = await Promise.all([promptsAPI.listTemplates(), promptsAPI.getCostMetrics()])
    templates.value = Array.isArray(list) ? list : (list?.items || [])
    metrics.value = observability?.prompts || {}
  } finally { loading.value = false }
}

async function openVersions(row) {
  activePrompt.value = row
  histories.value = await promptsAPI.getTemplateHistory(row.prompt_key)
  versionA.value = histories.value[1]?.version || histories.value[0]?.version
  versionB.value = histories.value[0]?.version
  comparison.value = null
  versionVisible.value = true
}

async function compareVersions() { comparison.value = await promptsAPI.compareTemplates(activePrompt.value.prompt_key, versionA.value, versionB.value) }
async function rollback(row) {
  await ElMessageBox.confirm(`确认基于 v${row.version} 创建新的激活版本？`, '回滚 Prompt', { type: 'warning' })
  await promptsAPI.rollbackTemplate(activePrompt.value.prompt_key, row.version)
  ElMessage.success('Prompt 已回滚并生成新版本')
  await openVersions(activePrompt.value)
  await loadAll()
}
async function openRuns(row) {
  runs.value = (await promptsAPI.listPromptRuns({ prompt_key: row.prompt_key, limit: 100 }))?.items || []
  runsVisible.value = true
}

onMounted(loadAll)
</script>

<style scoped>
.prompt-console { min-height: 100vh; padding: 24px; background: #111315; color: #f2f3f5; }
.page-header { display: flex; align-items: center; gap: 14px; max-width: 1440px; margin: 0 auto 20px; }
.page-header div { flex: 1; }.page-header h1 { margin: 0; font-size: 24px; letter-spacing: 0; }.page-header p { margin: 5px 0 0; color: #92979f; }
.metrics-band { max-width: 1440px; margin: 0 auto 20px; display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); border: 1px solid #30343a; }
.metrics-band div { padding: 16px; border-right: 1px solid #30343a; }.metrics-band div:last-child { border-right: 0; }.metrics-band span { display: block; color: #92979f; font-size: 12px; }.metrics-band strong { display: block; margin-top: 8px; font-size: 22px; }
.content-tabs { max-width: 1440px; margin: auto; }.toolbar { display: flex; gap: 10px; margin-bottom: 14px; }.toolbar .el-input { max-width: 320px; }.toolbar .el-select { width: 160px; }
.version-picker { display: flex; gap: 10px; margin-bottom: 16px; }.compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0; }.compare-grid pre { min-height: 220px; max-height: 420px; overflow: auto; padding: 12px; border: 1px solid #dcdfe6; white-space: pre-wrap; word-break: break-word; }
@media (max-width: 760px) { .prompt-console { padding: 14px; }.metrics-band { grid-template-columns: repeat(2, 1fr); }.compare-grid { grid-template-columns: 1fr; }.toolbar { flex-wrap: wrap; } }
</style>
