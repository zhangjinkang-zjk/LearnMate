import httpClient from './httpClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

// FastAPI 的 422 会把逐字段的校验错误放在 detail 数组里（每项含 loc/msg/type）。
// 原样丢给页面，会被 Vue 的文本插值 JSON.stringify 成一段结构体直接画在屏幕上
// （用户看到的就是那个）。这里压成一句人话。
const FIELD_LABELS = {
  identity: '身份',
  direction: '学习方向',
  goal: '学习目标',
  session_id: '诊断会话',
  question_id: '题目',
  answer: '回答',
  max_steps: '题目数量',
}

function describeValidationDetail(detail) {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return ''
  const seen = new Set()
  const parts = []
  for (const item of detail) {
    const field = Array.isArray(item?.loc) ? String(item.loc[item.loc.length - 1]) : ''
    const label = FIELD_LABELS[field] || field
    const reason = item?.type === 'string_too_short' ? '不能为空'
      : item?.type === 'string_too_long' ? '超出长度限制'
        : '填写不正确'
    const text = label ? `${label}${reason}` : (item?.msg || '有内容不符合要求')
    if (!seen.has(text)) {
      seen.add(text)
      parts.push(text)
    }
  }
  if (!parts.length) return ''
  return `${parts.join('、')}，请返回上一步补齐后重试。`
}

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
      detail = describeValidationDetail(body.detail) || body.msg || detail
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
  let streamError = ''
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
        if (event.type === 'error') streamError = event.message || '诊断服务暂时不可用'
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
  if (!finalResult) throw new Error(streamError || '流式响应未返回有效结果')
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
