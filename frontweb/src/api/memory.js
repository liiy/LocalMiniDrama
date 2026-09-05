/**
 * @file memory.js
 * @description 长期记忆系统与小说 RAG 知识库前端 API 客户端。
 * 支持记忆检索、LlamaIndex 语义滑动切片预览、Qdrant 剧本向量隔离集合生命周期管理。
 */
import request from '@/utils/request'

export const memoryAPI = {
  /**
   * 检索记忆条目（支持关键词与语义检索）
   * @param {Object} params - { drama_id, episode_id, q/query, memory_type, limit }
   */
  search(params) {
    return request.get('/platform/memory/search', { params: params || {} })
  },

  /**
   * 语义向量检索（POST 支持长向量 payload）
   * @param {Object} data - { drama_id, episode_id, query, query_vector, memory_type, limit }
   */
  searchVector(data) {
    return request.post('/platform/memory/search', data || {})
  },

  /**
   * 手动添加单条记忆条目
   * @param {Object} data - { drama_id, episode_id, memory_type, title, content, metadata }
   */
  addItem(data) {
    return request.post('/platform/memory', data || {})
  },

  /**
   * 获取 Qdrant 向量库连接与配置状态
   */
  getVectorSettings() {
    return request.get('/platform/memory/vector-settings')
  },

  /**
   * 查询指定剧本或全局 Qdrant 隔离集合诊断信息与向量数量
   * @param {number|string} dramaId - 剧本 ID
   */
  getVectorInfo(dramaId) {
    return request.get('/platform/memory/vectors/info', {
      params: dramaId ? { drama_id: dramaId } : {}
    })
  },

  /**
   * 按剧本维度批量清理 Qdrant 向量索引并重置 memory_items.embedding_ref
   * @param {number|string} dramaId - 剧本 ID
   */
  cleanDramaVectors(dramaId) {
    return request.post('/platform/memory/vectors/clean', { drama_id: Number(dramaId) })
  },

  /**
   * 删除剧本专属 Qdrant Collection 集合
   * @param {number|string} dramaId - 剧本 ID
   */
  deleteDramaCollection(dramaId) {
    return request.delete('/platform/memory/vectors/collection', {
      params: { drama_id: Number(dramaId) }
    })
  },

  /**
   * 小说文本 LlamaIndex 语义断句与自适应滑动窗口切片 (Overlap Chunking) 预览
   * @param {Object} data - { text, max_chapters, chunk_size, chunk_overlap, semantic_chunking }
   */
  previewSemanticSplit(data) {
    return request.post('/dramas/novel-slices/semantic-split', data || {})
  }
}

export default memoryAPI
