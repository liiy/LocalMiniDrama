import request from '@/utils/request'

/**
 * 剧本创作工坊 V2.0 API 接口封装
 * 对接 Python 后端 /api/v1/script-studio 相关路由
 */
export const scriptStudioAPI = {
  /**
   * 启动 LangGraph 五阶段创作流水线
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { user_prompt, genre, total_episodes, commercial_tag, hitl_mode }
   */
  startPipeline(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/pipeline/start`, data)
  },

  /**
   * 获取状态机快照与 HITL 中断状态
   * @param {number|string} dramaId 短剧ID
   */
  getPipelineState(dramaId) {
    return request.get(`/script-studio/dramas/${dramaId}/pipeline/state`)
  },

  /**
   * 人工修改大纲或人设并更新状态机
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { updates, as_node }
   */
  updatePipelineState(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/pipeline/update-state`, data)
  },

  /**
   * 断点唤醒恢复流水线
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { resume_inputs }
   */
  resumePipeline(dramaId, data = {}) {
    return request.post(`/script-studio/dramas/${dramaId}/pipeline/resume`, data)
  },

  /**
   * 全剧剧本定稿锁定
   * @param {number|string} dramaId 短剧ID
   */
  lockDrama(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/lock`)
  },

  /**
   * 触发 Script-to-Visual Bridge 契约同步视听工坊
   * @param {number|string} dramaId 短剧ID
   */
  syncVisual(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/sync-visual`)
  },

  /**
   * 单集 AST 局部定向修补
   * @param {number|string} dramaId 短剧ID
   * @param {number|string} episodeNum 分集序号
   * @param {Object} data { issues, deductions }
   */
  patchEpisode(dramaId, episodeNum, data) {
    return request.post(`/script-studio/dramas/${dramaId}/episodes/${episodeNum}/patch`, data)
  },

  /**
   * 大纲变更级联失效
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { changed_episode_num }
   */
  cascadeInvalidate(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/cascade-invalidate`, data)
  }
}
