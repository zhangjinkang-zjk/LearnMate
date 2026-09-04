import httpClient from './httpClient'

export const authApi = {
  async login(username, password) {
    const response = await httpClient.post('/user/login_user', { username, password })
    const body = response?.data || {}
    if (body.code !== 200 || !body.data?.token) throw new Error(body.msg || '登录失败，请检查账号和密码')
    return body.data
  },

  async sendEmailCode(email) {
    const response = await httpClient.post('/user/send_email_code', { email, purpose: 'register' })
    const body = response?.data || {}
    if (body.code !== 200) throw new Error(body.msg || '验证码发送失败，请稍后重试')
    return body
  },

  async registerByEmail(username, email, password, code) {
    const response = await httpClient.post('/user/register_by_email', {
      username,
      email,
      password,
      code,
    })
    const body = response?.data || {}
    const token = body.data?.token || body.data?.id
    if (body.code !== 200 || !token) throw new Error(body.msg || '注册失败，请检查邮箱验证码')
    return { ...body.data, token }
  },

  async readUser() {
    const response = await httpClient.get('/user/read_user')
    const body = response?.data || {}
    if (body.code !== 200 || !body.data) throw new Error(body.msg || '登录状态无效')
    return body.data
  },
}
