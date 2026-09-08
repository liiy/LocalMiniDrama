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
  },

  /**
   * 保存创意立项与高概念数据
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { concept_design, title?, description? }
   */
  saveConceptDesign(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/concept`, data)
  },

  /**
   * 重新生成阶段 1 创意立项高概念与四幕大纲
   * @param {number|string} dramaId 短剧ID
   */
  regenerateConcept(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/concept/regenerate`)
  },

  /**
   * 保存故事圣经与世界观数据
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { bible_design }
   */
  saveBibleDesign(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/bible`, data)
  },

  /**
   * 重新生成故事圣经与世界观
   * @param {number|string} dramaId 短剧ID
   */
  regenerateBible(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/bible/regenerate`)
  },

  /**
   * 一键从剧本正文抽取核心道具
   * @param {number|string} dramaId 短剧ID
   */
  extractProps(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/bible/extract-props`)
  },

  /**
   * 保存三级大纲数据
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { two_level_acts?, three_level_beats?, main_scenes_pool? }
   */
  saveOutlineDesign(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/outline`, data)
  },

  /**
   * 重新生成三级大纲
   * @param {number|string} dramaId 短剧ID
   */
  regenerateOutline(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/outline/regenerate`)
  },

  /**
   * 校验三级大纲 5 项工业化约束指标
   * @param {number|string} dramaId 短剧ID
   */
  validateOutline(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/outline/validate`)
  },

  /**
   * 获取所有分集导航列表
   * @param {number|string} dramaId 短剧ID
   */
  getEpisodesList(dramaId) {
    return request.get(`/script-studio/dramas/${dramaId}/episodes/list`)
  },

  /**
   * 获取指定分集的 AST 4分块详细剧本与质检雷达报告
   * @param {number|string} dramaId 短剧ID
   * @param {number|string} episodeNum 分集集数
   */
  getEpisodeDetail(dramaId, episodeNum) {
    return request.get(`/script-studio/dramas/${dramaId}/episodes/${episodeNum}/detail`)
  },

  /**
   * 保存指定分集的剧本内容与 AST 分块
   * @param {number|string} dramaId 短剧ID
   * @param {number|string} episodeNum 分集集数
   * @param {Object} data { title, commercial_tag, scenes, characters, props, ast_blocks, qa_score, radar_scores, qa_patches, character_info_gaps }
   */
  saveEpisodeScript(dramaId, episodeNum, data) {
    return request.post(`/script-studio/dramas/${dramaId}/episodes/${episodeNum}/save`, data)
  },

  /**
   * 重新生成本集剧本
   * @param {number|string} dramaId 短剧ID
   * @param {number|string} episodeNum 分集集数
   */
  regenerateEpisodeScript(dramaId, episodeNum) {
    return request.post(`/script-studio/dramas/${dramaId}/episodes/${episodeNum}/regenerate`)
  },

  /**
   * 从本集起续写后续分集
   * @param {number|string} dramaId 短剧ID
   * @param {number|string} episodeNum 分集集数
   */
  continueFromEpisode(dramaId, episodeNum) {
    return request.post(`/script-studio/dramas/${dramaId}/episodes/${episodeNum}/continue-from`)
  },

  /**
   * 批量生成指定集数范围正文
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { start_episode, end_episode, batch_size }
   */
  batchGenerateEpisodes(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/episodes/batch-generate`, data)
  },

  /**
   * 新增单集
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { episode_number?, title, commercial_tag?, description?, duration? }
   */
  addSingleEpisode(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/episodes/add`, data)
  },

  /**
   * 获取阶段 5 全剧复盘定稿看板与归宿校验数据
   * @param {number|string} dramaId 短剧ID
   */
  getFinalizeAudit(dramaId) {
    return request.get(`/script-studio/dramas/${dramaId}/finalize-audit`)
  },

  /**
   * 解除全剧定稿锁定
   * @param {number|string} dramaId 短剧ID
   */
  unlockDrama(dramaId) {
    return request.post(`/script-studio/dramas/${dramaId}/unlock`)
  },

  /**
   * 低分集 AST 原位自愈修补
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { episode_num, target_score? }
   */
  healEpisode(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/heal-episode`, data)
  },

  /**
   * 伏笔闭环一键补全
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { clue_id, recover_episode? }
   */
  healClue(dramaId, data) {
    return request.post(`/script-studio/dramas/${dramaId}/heal-clue`, data)
  },

  /**
   * 导出中心：全剧剧本与交付包导出
   * @param {number|string} dramaId 短剧ID
   * @param {Object} data { export_type?, include_storyboards?, include_qa_report? }
   */
  exportScript(dramaId, data = {}) {
    return request.post(`/script-studio/dramas/${dramaId}/export`, data)
  }
}

