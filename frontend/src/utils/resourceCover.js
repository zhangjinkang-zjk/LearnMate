const API_ORIGIN = String(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:2221').replace(/\/$/, '')

const TYPE_LABELS = {
  document: 'DOCUMENT',
  reading: 'READING',
  ppt: 'PRESENTATION',
  mindmap: 'KNOWLEDGE MAP',
  exercise: 'PRACTICE',
  case: 'CASE STUDY',
  video: 'VIDEO LESSON',
  external_video: 'VIDEO LESSON',
}

const PALETTES = {
  document: ['#183d34', '#dff15b'],
  reading: ['#334a63', '#dcebf7'],
  ppt: ['#6f4b2d', '#f4dc9a'],
  mindmap: ['#315978', '#d1e8f4'],
  exercise: ['#7a3f39', '#f4c9b8'],
  case: ['#5f4a78', '#e6d8f4'],
  video: ['#733d35', '#f5c6ae'],
  external_video: ['#733d35', '#f5c6ae'],
}

// 导出给需要「只判断有没有真封面、不要占位图」的地方用（如外部视频播放视图）。
// 那边缺封面时宁可保留自己的图标视图，也不要一张把标题写进图里的占位图 —— 标题在下面还会再显示一次。
export function asHttpUrl(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (/^https?:\/\//i.test(text)) return text
  if (/^\/(?:assets|src|@fs)\//.test(text)) return text
  if (text.startsWith('/')) return `${API_ORIGIN}${text}`
  return ''
}

function extractYouTubeId(value) {
  const text = String(value || '')
  const match = text.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([\w-]{6,})/i)
  return match?.[1] || ''
}

function escapeXml(value) {
  return String(value || '').replace(/[<>&'\"]/g, (character) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[character]))
}

export function generatedResourceCover(resource = {}) {
  const type = String(resource.resource_type || 'document').toLowerCase()
  const [background, accent] = PALETTES[type] || PALETTES.document
  const label = TYPE_LABELS[type] || 'LEARNING RESOURCE'
  const title = String(resource.title || resource.topic || 'Learning resource').trim().slice(0, 34)
  const safeTitle = escapeXml(title)
  const safeLabel = escapeXml(label)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="300" viewBox="0 0 720 300"><rect width="720" height="300" fill="${background}"/><circle cx="610" cy="-20" r="170" fill="${accent}" opacity=".16"/><circle cx="680" cy="242" r="115" fill="${accent}" opacity=".12"/><path d="M0 250H720" stroke="${accent}" stroke-opacity=".2" stroke-width="2"/><path d="M48 62h148M48 78h88" stroke="${accent}" stroke-opacity=".56" stroke-width="3" stroke-linecap="round"/><text x="48" y="138" fill="${accent}" font-family="Arial,Microsoft YaHei,sans-serif" font-size="16" font-weight="700" letter-spacing="2">${safeLabel}</text><text x="48" y="184" fill="#fff" font-family="Arial,Microsoft YaHei,sans-serif" font-size="28" font-weight="700">${safeTitle}</text><text x="48" y="244" fill="#fff" fill-opacity=".62" font-family="Arial,sans-serif" font-size="12" letter-spacing="3">LEARNMATE RESOURCE</text><rect x="582" y="62" width="64" height="64" rx="14" fill="${accent}" fill-opacity=".9"/><path d="M603 95h22M614 84v22" stroke="${background}" stroke-width="5" stroke-linecap="round"/></svg>`
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`
}

export function resourceCoverUrl(resource = {}) {
  const explicit = asHttpUrl(resource.cover_url || resource.thumbnail_url || resource.thumbnail)
  if (explicit) return explicit

  const pageUrl = resource.page_url || resource.file_url || resource.url || ''
  const youtubeId = extractYouTubeId(pageUrl)
  if (youtubeId) return `https://i.ytimg.com/vi/${youtubeId}/hqdefault.jpg`

  return generatedResourceCover(resource)
}
