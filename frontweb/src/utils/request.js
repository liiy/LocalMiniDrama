import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const TOKEN_KEY = 'lmd_api_token'
let isPromptingToken = false

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 600000,
  headers: { 'Content-Type': 'application/json' }
})

// 请求拦截器：自动注入 Token (支持 localStorage 和 sessionStorage)
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
      config.headers['x-lmd-token'] = token
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：处理成功、401 鉴权弹窗以及通用错误
request.interceptors.response.use(
  (response) => {
    // blob 类型直接返回原始数据，不做 JSON 解包
    if (response.config?.responseType === 'blob') {
      return response.data
    }
    const res = response.data
    if (res.success !== false) {
      return res.data !== undefined ? res.data : res
    }
    return Promise.reject(new Error(res.error?.message || '请求失败'))
  },
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    const backendMsg = error.response?.data?.error?.message || error.response?.data?.detail
    
    // 如果是登录接口自身返回 401 或处于登录页面，直接 reject，由登录页面处理
    const isLoginReq = url.includes('/auth/login') || url.includes('/auth/status')
    const isLoginPage = window.location.pathname === '/login'

    if (status === 401 && !isLoginReq && !isLoginPage) {
      if (!isPromptingToken) {
        isPromptingToken = true
        ElMessageBox.confirm(
          backendMsg || '后端已开启接口安全验证，当前未提供有效访问令牌 (API Token)。',
          '系统安全访问验证',
          {
            confirmButtonText: '前往授权登录页',
            cancelButtonText: '直接输入 Token',
            distinguishCancelAndClose: true,
            type: 'warning'
          }
        ).then(() => {
          const currentPath = encodeURIComponent(window.location.pathname + window.location.search)
          window.location.href = `/login?redirect=${currentPath}`
        }).catch((action) => {
          if (action === 'cancel') {
            ElMessageBox.prompt('请输入访问令牌（API Token）：', '快速输入 Token', {
              confirmButtonText: '确定并保存',
              cancelButtonText: '取消',
              inputType: 'password',
              inputValue: localStorage.getItem(TOKEN_KEY) || '',
              inputPlaceholder: '请输入 config.yaml 或 .env 中配置的 api_token',
              inputValidator: (val) => (!val ? 'Token 不能为空' : true)
            }).then(({ value }) => {
              localStorage.setItem(TOKEN_KEY, value.trim())
              ElMessage.success('Token 已保存，正在刷新...')
              setTimeout(() => {
                window.location.reload()
              }, 400)
            }).catch(() => {
              ElMessage.warning('未提供有效 Token，请求受限')
            })
          }
        }).finally(() => {
          isPromptingToken = false
        })
      }
      return Promise.reject(error)
    }

    // 提取后端实际错误信息（优先 API 返回的 message，而非 axios 通用 "status code 500"）
    const msg = backendMsg || error.message || '网络错误'
    ElMessage.error(msg)
    // 将真实错误信息写回 message，使组件 catch 块可直接用 e.message 获取可读内容
    if (backendMsg) error.message = backendMsg
    return Promise.reject(error)
  }
)

export default request
