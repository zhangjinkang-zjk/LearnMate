import httpClient from './httpClient'

async function request(method, path, options = {}) {
  try {
    const response = await httpClient.request({ method, url: path, ...options })
    const body = response.data
    if (body.code !== 200) throw new Error(body.msg || '操作失败，请重试')
    return body.data
  } catch (error) {
    const detail = error.response?.data?.detail
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? '输入内容不符合要求，请检查后重试' : error.message || '请求失败')
  }
}

export const adminApi = {
  resources: (params) => request('get', '/admin/resource-catalog', { params }),
  resource: (id) => request('get', `/admin/resources/${id}/detail`),
  updateResource: (id, data) => request('put', `/admin/resources/${id}`, { data }),
  review: (id, approved, reason = '') => request('post', `/admin/resources/applications/${id}/${approved ? 'approve' : 'reject'}`, { data: { reason } }),
  deleteResource: (id) => request('delete', `/admin/resources/${id}`),
  users: (params) => request('get', '/admin/activity', { params }),
  userActivity: (id) => request('get', `/admin/users/${id}/activity`),
  updateUser: (id, data) => request('put', `/admin/users/${id}`, { data }),
  resetPassword: (id, password) => request('post', `/admin/users/${id}/reset_password`, { data: { new_password: password } }),
  deleteUser: (id) => request('delete', `/admin/users/${id}`, { data: { confirm: true } }),
  push: (data) => request('post', '/admin/resource-pushes', { data }),
}

export const assignmentApi = {
  list: () => request('get', '/study/assignments'),
  resource: (id) => request('get', `/resource/${id}`),
  complete: (id) => request('post', `/study/assignments/${id}/complete`),
}
