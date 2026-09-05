import request from '../utils/request.js'

/**
 * 平台 Multi-Agent 专家矩阵 API
 * 对应后端 /api/v1/platform/agents 契约
 */
export const agentsAPI = {
  // 获取所有受控专家 Agent 列表（含职责与默认绑定的技能）
  list() {
    return request.get('/platform/agents')
  },
  // 获取单个 Agent 详情
  get(agentName) {
    return request.get(`/platform/agents/${agentName}`)
  },
  // 单独执行/调试指定的 Agent
  execute(agentName, data = {}) {
    return request.post(`/platform/agents/${agentName}/execute`, data)
  },
}
