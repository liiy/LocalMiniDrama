<template>
  <main class="memory-page">
    <header class="page-header">
      <el-button circle title="返回项目列表" @click="$router.push('/')"><el-icon><ArrowLeft /></el-icon></el-button>
      <div><h1>记忆治理</h1><p>提炼、冲突、生命周期与召回质量</p></div>
    </header>
    <section class="toolbar">
      <el-input-number v-model="dramaId" :min="1" controls-position="right" placeholder="剧目 ID" />
      <el-input v-model="query" clearable placeholder="检索标题、正文或关键词" @keyup.enter="search" />
      <el-select v-model="status"><el-option label="全部状态" value="all" /><el-option label="有效" value="active" /><el-option label="冲突" value="conflict" /><el-option label="过期" value="expired" /></el-select>
      <el-button type="primary" :loading="loading" @click="search"><el-icon><Search /></el-icon>检索</el-button>
    </section>
    <section class="actions-band">
      <el-button @click="distillVisible = true">自动提炼</el-button>
      <el-button :loading="acting" @click="detectConflicts">冲突检测</el-button>
      <el-button :loading="acting" @click="expireMemories">过期淘汰</el-button>
      <el-button @click="evaluationVisible = true">召回评估</el-button>
    </section>
    <el-table v-loading="loading" :data="items" empty-text="暂无记忆">
      <el-table-column prop="id" label="ID" width="80" /><el-table-column prop="memory_type" label="类型" width="130" />
      <el-table-column prop="title" label="标题" min-width="180" /><el-table-column prop="summary" label="摘要" min-width="260" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="100" /><el-table-column prop="confidence" label="可信度" width="90" />
      <el-table-column prop="revision" label="修订" width="80"><template #default="{ row }">v{{ row.revision || 1 }}</template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="edit(row)">修订</el-button></template></el-table-column>
    </el-table>

    <el-dialog v-model="editVisible" title="人工修订记忆" width="680px">
      <el-form label-position="top"><el-form-item label="标题"><el-input v-model="form.title" /></el-form-item><el-form-item label="正文"><el-input v-model="form.content" type="textarea" :rows="8" /></el-form-item><el-form-item label="摘要"><el-input v-model="form.summary" type="textarea" :rows="3" /></el-form-item><el-form-item label="状态"><el-select v-model="form.status"><el-option label="有效" value="active" /><el-option label="禁用" value="disabled" /></el-select></el-form-item><el-form-item label="修订说明"><el-input v-model="form.revision_note" /></el-form-item></el-form>
      <template #footer><el-button @click="editVisible = false">取消</el-button><el-button type="primary" @click="saveRevision">保存修订</el-button></template>
    </el-dialog>

    <el-dialog v-model="distillVisible" title="自动提炼长期记忆" width="680px">
      <el-input v-model="distillText" type="textarea" :rows="10" placeholder="输入待提炼的剧情事实、会议决策或小说片段" />
      <template #footer><el-button @click="distillVisible = false">取消</el-button><el-button type="primary" @click="distill">提炼并入库</el-button></template>
    </el-dialog>

    <el-dialog v-model="evaluationVisible" title="召回质量评估" width="560px">
      <el-input v-model="evalQuery" placeholder="测试查询" /><el-input v-model="expectedIds" class="spaced" placeholder="期望记忆 ID，逗号分隔" />
      <el-descriptions v-if="evaluation" class="spaced" :column="3" border><el-descriptions-item label="Precision">{{ evaluation.precision }}</el-descriptions-item><el-descriptions-item label="Recall">{{ evaluation.recall }}</el-descriptions-item><el-descriptions-item label="MRR">{{ evaluation.mrr }}</el-descriptions-item></el-descriptions>
      <template #footer><el-button @click="evaluationVisible = false">关闭</el-button><el-button type="primary" @click="evaluate">执行评估</el-button></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ArrowLeft, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { memoryAPI } from '@/api/prompts'

const dramaId = ref(1), query = ref(''), status = ref('all'), items = ref([])
const loading = ref(false), acting = ref(false), editVisible = ref(false), distillVisible = ref(false), evaluationVisible = ref(false)
const form = reactive({ id: null, title: '', content: '', summary: '', status: 'active', revision_note: '' })
const distillText = ref(''), evalQuery = ref(''), expectedIds = ref(''), evaluation = ref(null)

async function search() {
  loading.value = true
  try { items.value = await memoryAPI.search({ drama_id: dramaId.value, q: query.value || undefined, status: status.value, limit: 100 }) }
  finally { loading.value = false }
}
function edit(row) { Object.assign(form, { id: row.id, title: row.title || '', content: row.content || '', summary: row.summary || '', status: row.status || 'active', revision_note: '' }); editVisible.value = true }
async function saveRevision() { await memoryAPI.update(form.id, { ...form, editor: 'web_console' }); editVisible.value = false; ElMessage.success('记忆修订已保存'); await search() }
async function distill() { await memoryAPI.distill({ drama_id: dramaId.value, content: distillText.value }); distillVisible.value = false; distillText.value = ''; ElMessage.success('长期记忆已提炼'); await search() }
async function detectConflicts() { acting.value = true; try { const res = await memoryAPI.detectConflicts({ drama_id: dramaId.value }); ElMessage.success(`检测完成，发现 ${res.conflict_count || 0} 组冲突`); await search() } finally { acting.value = false } }
async function expireMemories() { acting.value = true; try { const res = await memoryAPI.expire(); ElMessage.success(`已淘汰 ${res.expired_count || 0} 条过期记忆`); await search() } finally { acting.value = false } }
async function evaluate() { evaluation.value = await memoryAPI.evaluateRetrieval({ drama_id: dramaId.value, query: evalQuery.value, expected_ids: expectedIds.value.split(',').map(v => v.trim()).filter(Boolean), limit: 20 }) }
</script>

<style scoped>
.memory-page { min-height: 100vh; padding: 24px; background: #111315; color: #f2f3f5; }.page-header { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; }.page-header h1 { margin: 0; font-size: 24px; letter-spacing: 0; }.page-header p { margin: 5px 0 0; color: #92979f; }
.toolbar { display: grid; grid-template-columns: 150px minmax(240px, 1fr) 150px auto; gap: 10px; margin-bottom: 12px; }.actions-band { display: flex; gap: 8px; padding: 12px 0; border-top: 1px solid #30343a; border-bottom: 1px solid #30343a; margin-bottom: 16px; }.spaced { margin-top: 14px; }
@media (max-width: 760px) { .memory-page { padding: 14px; }.toolbar { grid-template-columns: 1fr; }.actions-band { flex-wrap: wrap; } }
</style>
