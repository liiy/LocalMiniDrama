import request from '@/utils/request'

/**
 * 提示词管理与平台 Prompt Registry API
 * 对齐后端 /api/v1/settings/prompts 及 /api/v1/platform/prompts 接口契约
 */
export const promptsAPI = {
  // 基础提示词覆盖配置（对齐 legacy 9大系统提示词）
  list() {
    return request.get('/settings/prompts')
  },
  update(key, content) {
    return request.put(`/settings/prompts/${key}`, { content })
  },
  reset(key) {
    return request.delete(`/settings/prompts/${key}`)
  },

  // Phase 2: 平台化统一 Prompt Registry 模板服务
  listTemplates(params) {
    return request.get('/platform/prompts', { params })
  },
  getTemplate(templateIdOrKey) {
    return request.get(`/platform/prompts/${templateIdOrKey}`)
  },
  createTemplate(data) {
    return request.post('/platform/prompts', data)
  },
  upsertTemplate(data) {
    return request.post('/platform/prompts', data)
  },
  getTemplateHistory(promptKey) {
    return request.get(`/platform/prompts/${promptKey}/history`)
  },
  rollbackTemplate(promptKey, targetVersion) {
    return request.post(`/platform/prompts/${promptKey}/rollback`, { target_version: targetVersion })
  },
  compareTemplates(promptKey, versionA, versionB) {
    return request.get(`/platform/prompts/${promptKey}/compare`, {
      params: {
        version_a: versionA,
        version_b: versionB,
      },
    })
  },
  renderPrompt(promptKey, variables = {}, version = null) {
    return request.post('/platform/prompts/render', {
      prompt_key: promptKey,
      variables,
      version,
    })
  },

  // Phase 2: Prompt Run 执行链路审计与快照
  listPromptRuns(params) {
    // 使用无动态路由冲突的新地址；后端保留旧地址用于兼容。
    return request.get('/platform/prompt-runs', { params })
  },
  getPromptRun(runId) {
    return request.get(`/platform/prompt-runs/${runId}`)
  },
  recordPromptRun(data) {
    return request.post('/platform/prompts/runs', data)
  },
  // 汇总 Prompt 调用次数、Token、成本、延迟及分组明细。
  getCostMetrics() {
    return request.get('/platform/observability/metrics')
  },
}

/**
 * 长期记忆、小说 RAG 与上下文快照 API
 * 对齐后端 /api/v1/platform/memory 及 /api/v1/platform/context 接口契约
 */
export const memoryAPI = {
  search(params) {
    return request.get('/platform/memory/search', { params })
  },
  searchVector(data) {
    return request.post('/platform/memory/search', data)
  },
  create(data) {
    return request.post('/platform/memory', data)
  },
  update(memoryId, data) {
    return request.patch(`/platform/memory/${memoryId}`, data)
  },
  distill(data) {
    return request.post('/platform/memory/distill', data)
  },
  detectConflicts(data = {}) {
    return request.post('/platform/memory/conflicts/detect', data)
  },
  expire(data = {}) {
    return request.post('/platform/memory/expire', data)
  },
  evaluateRetrieval(data) {
    return request.post('/platform/memory/retrieval-evaluations', data)
  },
  buildContext(data) {
    return request.post('/platform/context/build', data)
  },
  getContextSnapshot(snapshotId) {
    return request.get(`/platform/context/snapshots/${snapshotId}`)
  },
}

/**
 * 全局生成并发与超时设置 API
 * 对齐后端 /api/v1/settings/generation 接口契约
 */
export const generationSettingsAPI = {
  get() {
    return request.get('/settings/generation')
  },
  update(data) {
    return request.put('/settings/generation', data)
  },
}


