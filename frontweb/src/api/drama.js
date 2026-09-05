import request from '@/utils/request'

export const dramaAPI = {
  list(params) {
    return request.get('/dramas', { params: params || {} })
  },
  create(data) {
    return request.post('/dramas', data)
  },
  get(id) {
    return request.get(`/dramas/${id}`)
  },
  update(id, data) {
    return request.put(`/dramas/${id}`, data)
  },
  delete(id) {
    return request.delete(`/dramas/${id}`)
  },
  saveEpisodes(id, episodes) {
    return request.put(`/dramas/${id}/episodes`, { episodes })
  },
  saveCharacters(id, data) {
    return request.put(`/dramas/${id}/characters`, data)
  },
  /** 保存梗概/故事摘要到项目（outline），body: { summary, title?, genre?, tags? } */
  saveOutline(id, data) {
    return request.put(`/dramas/${id}/outline`, data)
  },
  saveProgress(id, data) {
    return request.put(`/dramas/${id}/progress`, data)
  },
  saveCanvasLayout(id, canvasLayout, workflowGroups) {
    const body = {}
    if (canvasLayout != null) body.canvas_layout = canvasLayout
    if (workflowGroups !== undefined) body.workflow_groups = workflowGroups
    return request.put(`/dramas/${id}/canvas-layout`, body)
  },
  getStoryboards(episodeId) {
    return request.get(`/episodes/${episodeId}/storyboards`)
  },
  generateStoryboard(episodeId, options) {
    // 兼容旧调用方式: generateStoryboard(episodeId, model, style)
    let body = {};
    if (arguments.length > 2 || typeof options === 'string') {
       body.model = arguments[1];
       body.style = arguments[2];
    } else {
       body = options || {};
    }
    return request.post(`/episodes/${episodeId}/storyboards`, body)
  },
  finalizeEpisode(episodeId, data) {
    return request.post(`/episodes/${episodeId}/finalize`, data || {})
  },
  extractBackgrounds(episodeId, body) {
    return request.post(`/images/episode/${episodeId}/backgrounds/extract`, body || {})
  },
  extractEpisodeCharacters(episodeId) {
    return request.post(`/episodes/${episodeId}/characters/extract`)
  },
  exportDrama(id) {
    return request.get(`/dramas/${id}/export`, { responseType: 'blob' })
  },
  importDrama(file) {
    const form = new FormData()
    form.append('file', file)
    return request.post('/dramas/import', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  listExamples() {
    return request.get('/dramas/examples')
  },
  importExample(filename) {
    return request.post('/dramas/import-example', { filename })
  },
  /**
   * 导入小说并执行语义层级切片与滑动窗口持久化
   * @param {FormData|Object} data
   */
  importNovel(data) {
    if (data instanceof FormData) {
      return request.post('/dramas/import-novel', data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
    }
    return request.post('/dramas/import-novel', data || {})
  },
  /**
   * 获取指定剧本在 Qdrant 中的向量集合信息与索引量
   */
  getVectorMemoryInfo(dramaId) {
    return request.get(`/dramas/${dramaId}/memory/vectors/info`)
  },
  /**
   * 批量清理剧本专属的 Qdrant 向量索引
   */
  cleanVectorMemory(dramaId) {
    return request.delete(`/dramas/${dramaId}/memory/vectors`)
  },
  /**
   * 删除剧本专属的 Qdrant Collection
   */
  deleteVectorCollection(dramaId) {
    return request.delete(`/dramas/${dramaId}/memory/collection`)
  }
}
