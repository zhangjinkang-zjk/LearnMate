import httpClient from './httpClient'

export const authApi = {
  async login(username, password) {
    const response = await httpClient.post('/user/login_user', { username, password })
    const body = response?.data || {}
    if (body.code !== 200 || !body.data?.token) throw new Error(body.msg || '登录失败，请检查账号和密码')
    return body.data
  },

  async readUser() {
    const response = await httpClient.get('/user/read_user')
    const body = response?.data || {}
    if (body.code !== 200 || !body.data) throw new Error(body.msg || '登录状态无效')
    return body.data
  },
}
