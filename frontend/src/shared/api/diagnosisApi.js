import httpClient from './httpClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

async function streamRequest(path, payload, onEvent) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const token = localStorage.getItem('token')
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, token } : {}),
      'ngrok-skip-browser-warning': 'true',
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      detail = body.detail || body.msg || detail
    } catch { /* 保留状态码错误 */ }
    const error = new Error(detail)
    error.response = { status: response.status, data: { detail } }
    throw error
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResult = null
  const consume = (chunk) => {
    buffer += chunk
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const data = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('')
      if (!data || data === '[DONE]') continue
      try {
        const event = JSON.parse(data)
        if (event.type === 'result') finalResult = event.data
        onEvent?.(event)
      } catch { /* 忽略跨帧或代理附加的非 JSON 行 */ }
    }
  }
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    consume(decoder.decode(value, { stream: true }))
  }
  consume(decoder.decode())
  if (!finalResult) throw new Error('流式响应未返回有效结果')
  return finalResult
}

export const diagnosisApi = {
  async start(payload) {
    const response = await httpClient.post('/learning/diagnosis/start', payload)
    return unwrap(response)
  },
  async answer(payload) {
    const response = await httpClient.post('/learning/diagnosis/answer', payload)
    return unwrap(response)
  },
  startStream(payload, onEvent) {
    return streamRequest('/learning/diagnosis/start/stream', payload, onEvent)
  },
  answerStream(payload, onEvent) {
    return streamRequest('/learning/diagnosis/answer/stream', payload, onEvent)
  },
}
