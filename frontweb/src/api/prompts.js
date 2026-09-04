import request from '@/utils/request'

export const promptsAPI = {
  list() {
    return request.get('/settings/prompts')
  },
  update(key, content) {
    return request.put(`/settings/prompts/${key}`, { content })
  },
  reset(key) {
    return request.delete(`/settings/prompts/${key}`)
  },
  // Phase 2: 统一平台 Prompt Registry API
  listTemplates(params) {
    return request.get('/platform/prompts/templates', { params })
  },
  getTemplate(templateId) {
    return request.get(`/platform/prompts/templates/${templateId}`)
  },
  createTemplate(data) {
    return request.post('/platform/prompts/templates', data)
  },
  getTemplateHistory(promptKey) {
    return request.get(`/platform/prompts/templates/${promptKey}/history`)
  },
  rollbackTemplate(promptKey, targetVersion) {
    return request.post(`/platform/prompts/templates/${promptKey}/rollback`, { target_version: targetVersion })
  },
  compareTemplates(promptKey, v1, v2) {
    return request.get(`/platform/prompts/templates/${promptKey}/compare`, { params: { v1, v2 } })
  },
  // Phase 2: Prompt Run 审计与快照
  listPromptRuns(params) {
    return request.get('/platform/prompts/runs', { params })
  },
  getPromptRun(runId) {
    return request.get(`/platform/prompts/runs/${runId}`)
  },
}

export const memoryAPI = {
  // Phase 2: 长期记忆与 RAG 检索
  search(params) {
    return request.get('/platform/memory/search', { params })
  },
  create(data) {
    return request.post('/platform/memory', data)
  },
  buildContext(data) {
    return request.post('/platform/context/build', data)
  },
  getContextSnapshot(snapshotId) {
    return request.get(`/platform/context/snapshots/${snapshotId}`)
  },
}

export const generationSettingsAPI = {
  get() {
    return request.get('/settings/generation')
  },
  update(data) {
    return request.put('/settings/generation', data)
  },
}

