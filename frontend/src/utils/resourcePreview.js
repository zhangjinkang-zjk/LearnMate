const LABELS = {
  topic: '主题',
  title: '标题',
  summary: '摘要',
  description: '说明',
  content: '内容',
}

function tryParseJson(value) {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text || !/^[{[]/.test(text)) return value
  try {
    return JSON.parse(text)
  } catch {
    return value
  }
}

function renderValue(value, depth = 0) {
  const parsed = tryParseJson(value)
  if (parsed == null) return ''
  if (typeof parsed === 'string' || typeof parsed === 'number' || typeof parsed === 'boolean') return String(parsed)
  if (Array.isArray(parsed)) return parsed.map((item) => renderValue(item, depth)).filter(Boolean).join('\n\n')

  if (parsed.topic && Array.isArray(parsed.children)) {
    const heading = `${'  '.repeat(depth)}${depth ? '• ' : ''}${parsed.topic}`
    const children = parsed.children.map((item) => renderValue(item, depth + 1)).filter(Boolean).join('\n\n')
    return [heading, children].filter(Boolean).join('\n\n')
  }

  if (typeof parsed.content === 'string' && Object.keys(parsed).length <= 3) return parsed.content

  return Object.entries(parsed)
    .map(([key, item]) => {
      const label = LABELS[key] || key
      const rendered = renderValue(item, depth + 1)
      return rendered ? `${label}：${rendered}` : ''
    })
    .filter(Boolean)
    .join('\n\n')
}

export function formatResourcePreview(resource = {}) {
  const value = resource.preview ?? resource.content ?? resource.description ?? ''
  return renderValue(value).trim()
}
