import axios from 'axios'

const httpClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

httpClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
    config.headers.token = token
  }
  config.headers = config.headers || {}
  config.headers['ngrok-skip-browser-warning'] = 'true'
  return config
})

httpClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      const currentPath = window.location.hash.replace(/^#/, '') || '/'
      if (!currentPath.startsWith('/login')) window.location.hash = `#/login?redirect=${encodeURIComponent(currentPath)}`
    }
    return Promise.reject(error)
  },
)

export default httpClient
