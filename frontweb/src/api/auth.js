import request from '@/utils/request'

export const authAPI = {
  /** 获取鉴权状态（是否开启、当前 Token 是否有效等） */
  getStatus() {
    return request.get('/auth/status')
  },
  /** 使用 API Token 登录 */
  login(token) {
    return request.post('/auth/login', { token })
  },
  /** 退出登录 */
  logout() {
    return request.post('/auth/logout')
  }
}
