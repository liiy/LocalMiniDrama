import request from '@/utils/request'

/**
 * 平台级工作流 (Workflow DAG) 与任务队列调度 API
 * 对应后端 /api/v1/platform/workflows 及 /api/v1/platform/queue 契约
 */
export const workflowAPI = {
  // 获取工作流蓝图列表
  listBlueprints() {
    return request.get('/platform/workflows/blueprints')
  },
  // 获取单个工作流蓝图步骤
  getBlueprint(type) {
    return request.get(`/platform/workflows/blueprints/${type}`)
  },
  // 查询工作流运行实例列表
  list(params) {
    return request.get('/platform/workflows', { params })
  },
  // 查询指定工作流运行详情（含全量步骤）
  get(workflowRunId) {
    return request.get(`/platform/workflows/${workflowRunId}`)
  },
  // 获取工作流 DAG 执行依赖图与就绪节点状态
  getGraph(workflowRunId) {
    return request.get(`/platform/workflows/${workflowRunId}/graph`)
  },
  // 创建原创剧本创作流水线
  createOriginalScript(data) {
    return request.post('/platform/workflows/original-script', data)
  },
  // 创建小说改编短剧流水线
  createNovelAdaptation(data) {
    return request.post('/platform/workflows/novel-adaptation', data)
  },
  // 执行下一个就绪节点
  executeNext(workflowRunId, data = {}) {
    return request.post(`/platform/workflows/${workflowRunId}/execute-next`, data)
  },
  // 持续执行直至遇到人工审核或阻塞节点
  executeUntilBlocked(workflowRunId, data = {}) {
    return request.post(`/platform/workflows/${workflowRunId}/execute-until-blocked`, data)
  },
  // 执行指定步骤节点
  executeStep(workflowRunId, stepKey, data = {}) {
    return request.post(`/platform/workflows/${workflowRunId}/execute-step/${stepKey}`, data)
  },
  // 暂停工作流
  pause(workflowRunId) {
    return request.post(`/platform/workflows/${workflowRunId}/pause`)
  },
  // 恢复工作流
  resume(workflowRunId) {
    return request.post(`/platform/workflows/${workflowRunId}/resume`)
  },
  // 取消工作流
  cancel(workflowRunId, reason = '') {
    return request.post(`/platform/workflows/${workflowRunId}/cancel`, { reason })
  },
  // 局部重试特定步骤
  retryStep(workflowRunId, stepKey) {
    return request.post(`/platform/workflows/${workflowRunId}/retry-step/${stepKey}`)
  },
  /**
   * 人工审批放行工作流关键步骤 (Human-in-the-loop)
   * @param {string} workflowRunId 工作流 ID
   * @param {string} stepKey 步骤标识
   * @param {Object} [data] 审批数据
   * @param {string} [data.approver] 审批人
   * @param {string} [data.feedback] 审批反馈意见
   * @param {Object} [data.modified_output] 人工调整后的输出内容
   * @param {boolean} [data.auto_resume] 是否在审批后自动继续推进后续步骤
   */
  approveStep(workflowRunId, stepKey, data = {}) {
    return request.post(`/platform/workflows/${workflowRunId}/steps/${stepKey}/approve`, data)
  },
  /**
   * 人工驳回工作流关键步骤 (Human-in-the-loop)
   * @param {string} workflowRunId 工作流 ID
   * @param {string} stepKey 步骤标识
   * @param {Object} [data] 驳回数据
   * @param {string} [data.rejector] 驳回人
   * @param {string} [data.reason] 驳回原因及修改建议
   * @param {'retry'|'fail'} [data.action] 驳回后续动作（retry: 重置步骤重跑; fail: 终止工作流）
   */
  rejectStep(workflowRunId, stepKey, data = {}) {
    return request.post(`/platform/workflows/${workflowRunId}/steps/${stepKey}/reject`, data)
  },
  /**
   * 订阅工作流实时 SSE 事件流 (Server-Sent Events)
   * @param {string} workflowRunId 工作流运行 ID
   * @param {Object} options 回调配置
   * @param {Function} [options.onState] 状态更新回调 (包含工作流与所有步骤状态)
   * @param {Function} [options.onFinished] 工作流完成/失败/取消结束回调
   * @param {Function} [options.onError] 异常错误回调
   * @param {number} [options.interval] 后端轮询间隔 (秒)
   * @returns {{ close: Function }} 包含 close() 方法的控制器对象
   */
  subscribeStream(workflowRunId, options = {}) {
    const { onState, onFinished, onError, interval = 1 } = options
    const url = `/api/v1/platform/workflows/${workflowRunId}/stream?interval=${interval}`
    const eventSource = new EventSource(url)

    eventSource.addEventListener('workflow_state', (event) => {
      try {
        const data = JSON.parse(event.data)
        if (onState) onState(data)
      } catch (e) {
        console.error('解析 SSE workflow_state 失败', e)
      }
    })

    eventSource.addEventListener('workflow_finished', (event) => {
      try {
        const data = JSON.parse(event.data)
        if (onFinished) onFinished(data)
      } catch (e) {
        console.error('解析 SSE workflow_finished 失败', e)
      }
      eventSource.close()
    })

    eventSource.addEventListener('error', (event) => {
      if (onError) onError(event)
    })

    return {
      close() {
        eventSource.close()
      }
    }
  },
}

/**
 * 平台持久化任务队列 API
 */
export const queueAPI = {
  // 提交队列任务
  enqueue(data) {
    return request.post('/platform/queue/jobs', data)
  },
  // 查询队列任务列表
  listJobs(params) {
    return request.get('/platform/queue/jobs', { params })
  },
  // 查询 Worker 节点状态
  listWorkers(params) {
    return request.get('/platform/queue/workers', { params })
  },
  // 获取内嵌队列 Runtime 运行健康状态
  getRuntimeStatus() {
    return request.get('/platform/queue/runtime')
  },
  // 重试任务
  retryJob(jobId, data = {}) {
    return request.post(`/platform/queue/jobs/${jobId}/retry`, data)
  },
  // 取消任务
  cancelJob(jobId, reason = '') {
    return request.post(`/platform/queue/jobs/${jobId}/cancel`, { reason })
  },
  /**
   * 订阅队列任务实时 SSE 事件流
   * @param {string} jobId 任务 ID
   * @param {Object} options 回调配置
   * @returns {{ close: Function }} 控制器对象
   */
  subscribeStream(jobId, options = {}) {
    const { onUpdate, onFinished, onError, interval = 1 } = options
    const url = `/api/v1/platform/queue/jobs/${jobId}/stream?interval=${interval}`
    const eventSource = new EventSource(url)

    eventSource.addEventListener('job_update', (event) => {
      try {
        const data = JSON.parse(event.data)
        if (onUpdate) onUpdate(data)
      } catch (e) {
        console.error('解析 SSE job_update 失败', e)
      }
    })

    eventSource.addEventListener('job_finished', (event) => {
      try {
        const data = JSON.parse(event.data)
        if (onFinished) onFinished(data)
      } catch (e) {
        console.error('解析 SSE job_finished 失败', e)
      }
      eventSource.close()
    })

    eventSource.addEventListener('error', (event) => {
      if (onError) onError(event)
    })

    return {
      close() {
        eventSource.close()
      }
    }
  },
}
