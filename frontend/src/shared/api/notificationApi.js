import httpClient from './httpClient'

// /notification/list 用 {code,msg,data} 信封，/notification/unread-count 直接返回裸对象，
// 所以这里统一在 httpClient 的 data 上取一层：有 data 就用 data，没有就用响应本身。
const unwrap = (response) => {
  const payload = response?.data
  if (payload?.code && payload.code !== 200) {
    const error = new Error(payload.msg || '读取通知失败')
    error.response = { status: payload.code, data: { detail: error.message } }
    throw error
  }
  return payload?.data ?? payload ?? null
}

export const notificationApi = {
  async list(page = 1, size = 20) {
    const data = unwrap(await httpClient.get('/notification/list', { params: { page, size } }))
    return {
      items: Array.isArray(data?.items) ? data.items : [],
      total: Number(data?.total) || 0,
      unreadCount: Number(data?.unread_count) || 0,
    }
  },

  async unreadCount() {
    const data = unwrap(await httpClient.get('/notification/unread-count'))
    return Number(data?.unread_count) || 0
  },

  async markRead(notificationId) {
    return unwrap(await httpClient.post(`/notification/${notificationId}/read`))
  },

  async markAllRead() {
    return unwrap(await httpClient.post('/notification/read-all'))
  },
}
