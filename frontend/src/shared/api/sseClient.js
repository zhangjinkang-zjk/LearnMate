import { clearAuthSession } from '@/shared/auth/session'

function createHttpError(status, detail) {
  const error = new Error(detail || `请求失败（${status}）`)
  error.response = { status, data: { detail: error.message } }
  return error
}

async function readErrorDetail(response) {
  try {
    const payload = await response.json()
    return payload.detail || payload.msg || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

function handleUnauthorized() {
  clearAuthSession()
  const currentPath = window.location.hash.replace(/^#/, '') || '/'
  if (!currentPath.startsWith('/login')) {
    window.location.hash = `#/login?redirect=${encodeURIComponent(currentPath)}`
  }
}

export async function streamJsonEvents(path, payload, onEvent, options = {}) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const token = localStorage.getItem('token')
  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method || 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, token } : {}),
      'ngrok-skip-browser-warning': 'true',
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal: options.signal,
  })

  if (!response.ok) {
    if (response.status === 401) handleUnauthorized()
    throw createHttpError(response.status, await readErrorDetail(response))
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let lastEvent = null

  const consumeFrame = (frame) => {
    const rawData = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
      .join('\n')

    if (!rawData || rawData === '[DONE]') return
    let event
    try {
      event = JSON.parse(rawData)
    } catch {
      // Some reverse proxies append non-SSE text. Valid frames continue to be consumed.
      return
    }
    lastEvent = event
    onEvent?.(event)
  }

  const consume = (chunk, flush = false) => {
    buffer += chunk
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    frames.forEach(consumeFrame)
    if (flush && buffer.trim()) {
      consumeFrame(buffer)
      buffer = ''
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    consume(decoder.decode(value, { stream: true }))
  }
  consume(decoder.decode(), true)
  return lastEvent
}
