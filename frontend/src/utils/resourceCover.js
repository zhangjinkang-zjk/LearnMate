import { formatResourcePreview } from './resourcePreview'

const API_ORIGIN = String(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:2221').replace(/\/$/, '')

const TYPE_LABELS = {
  document: 'DOCUMENT',
  reading: 'READING',
  ppt: 'PRESENTATION',
  mindmap: 'KNOWLEDGE MAP',
  mind_map: 'KNOWLEDGE MAP',
  knowledge_map: 'KNOWLEDGE MAP',
  exercise: 'PRACTICE',
  case: 'CASE STUDY',
  video: 'VIDEO LESSON',
  external_video: 'VIDEO LESSON',
}

// 内部用：把封面值归一成可直接喂给 <img> 的地址。
// 曾短暂 export 给外部视频播放视图用（那边只要真封面、不要占位图），
// 但远端重构后播放视图已删除、封面改由 LearningVideoPanel 的卡片网格负责，故收回。
function asHttpUrl(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.startsWith('//')) return `https:${text}`
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

function contentLines(resource, limit = 3) {
  const raw = formatResourcePreview(resource)
    .replace(/<!--[^>]*-->/g, '')
    .replace(/[#*`>|_]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const words = raw ? raw.match(/.{1,18}/g) || [] : []
  return words.slice(0, limit).map(escapeXml)
}

function parseMindmapTopics(resource) {
  const fallback = contentLines(resource, 4)
  const value = resource.content ?? resource.preview
  if (!value) return fallback
  try {
    const parsed = typeof value === 'string'
      ? JSON.parse(value.replace(/^```(?:json|markdown|md)?\s*/i, '').replace(/```$/i, '').trim())
      : value
    const topics = []
    const collect = (node) => {
      if (!node || topics.length >= 5) return
      if (typeof node === 'string') { topics.push(node); return }
      const topic = node.topic || node.title || node.name || node.label || node.text
      if (topic) topics.push(String(topic))
      const children = node.children || node.nodes || node.nodeData?.children || []
      if (Array.isArray(children)) children.forEach(collect)
    }
    collect(parsed.nodeData || parsed.root || parsed.mindmap || parsed)
    return topics.length ? topics.slice(0, 5).map((topic) => escapeXml(topic.slice(0, 14))) : fallback
  } catch {
    return fallback
  }
}

function renderDocumentCover(resource, title) {
  const lines = contentLines(resource)
  const textLines = lines.length ? lines : [escapeXml(title.slice(0, 18)), 'Core concepts and notes', 'Examples and practice']
  return `<rect width="720" height="300" fill="#e8efe5"/><rect x="84" y="22" width="552" height="256" rx="9" fill="#fff"/><rect x="84" y="22" width="552" height="35" rx="9" fill="#1e3c34"/><circle cx="108" cy="39" r="5" fill="#d9ec72"/><circle cx="126" cy="39" r="5" fill="#8ba77a"/><path d="M122 88h270M122 100h190" stroke="#3f5b31" stroke-width="5" stroke-linecap="round"/><path d="M122 128h405M122 151h370M122 174h331M122 210h405" stroke="#d8e2d7" stroke-width="5" stroke-linecap="round"/><text x="122" y="132" fill="#24382f" font-family="Arial,Microsoft YaHei,sans-serif" font-size="17" font-weight="700">${textLines[0]}</text><text x="122" y="155" fill="#66776b" font-family="Arial,Microsoft YaHei,sans-serif" font-size="13">${textLines[1] || ''}</text><text x="122" y="178" fill="#66776b" font-family="Arial,Microsoft YaHei,sans-serif" font-size="13">${textLines[2] || ''}</text><rect x="484" y="210" width="104" height="24" rx="12" fill="#edf5e5"/><text x="505" y="227" fill="#3f5b31" font-family="Arial,sans-serif" font-size="10" font-weight="700">READING</text>`
}

function renderPptCover(resource, title) {
  const lines = contentLines(resource, 2)
  const heading = lines[0] || escapeXml(title.slice(0, 20))
  const subheading = lines[1] || 'Visual explanation'
  return `<rect width="720" height="300" fill="#253f56"/><rect x="54" y="34" width="612" height="232" rx="7" fill="#f8f7f1"/><rect x="54" y="34" width="612" height="28" rx="7" fill="#dce9e8"/><circle cx="78" cy="48" r="5" fill="#4d7c77"/><circle cx="95" cy="48" r="5" fill="#c6a566"/><rect x="92" y="90" width="260" height="20" rx="3" fill="#315978"/><rect x="92" y="123" width="210" height="9" rx="3" fill="#a6b7be"/><rect x="92" y="142" width="174" height="9" rx="3" fill="#c4cfd1"/><rect x="92" y="172" width="178" height="46" rx="5" fill="#e7f0ed"/><path d="M393 204l54-66 49 35 57-75 68 106z" fill="#bdd8cf"/><circle cx="547" cy="107" r="23" fill="#d8b75e"/><text x="92" y="243" fill="#263943" font-family="Arial,Microsoft YaHei,sans-serif" font-size="15" font-weight="700">${heading}</text><text x="92" y="263" fill="#617780" font-family="Arial,Microsoft YaHei,sans-serif" font-size="12">${subheading}</text>`
}

function renderMindmapCover(resource, title) {
  const topics = parseMindmapTopics(resource)
  const root = escapeXml((topics.shift() || title).slice(0, 16))
  const nodes = topics.length ? topics : ['Concepts', 'Process', 'Examples']
  const positions = [[458, 74], [524, 142], [462, 211], [246, 208]]
  const nodeMarkup = nodes.slice(0, 4).map((topic, index) => {
    const [x, y] = positions[index]
    return `<path d="M360 150L${x} ${y}" stroke="#8cb199" stroke-width="3"/><rect x="${x - 54}" y="${y - 17}" width="108" height="34" rx="17" fill="#f4f8ef" stroke="#a9c8ae"/><text x="${x}" y="${y + 4}" text-anchor="middle" fill="#3f5b31" font-family="Arial,Microsoft YaHei,sans-serif" font-size="11" font-weight="700">${topic}</text>`
  }).join('')
  return `<rect width="720" height="300" fill="#e7f0ef"/><path d="M0 44H720M0 256H720" stroke="#d1dfdb" stroke-width="1"/><circle cx="360" cy="150" r="57" fill="#315978"/><text x="360" y="146" text-anchor="middle" fill="#fff" font-family="Arial,Microsoft YaHei,sans-serif" font-size="14" font-weight="700">${root}</text><text x="360" y="166" text-anchor="middle" fill="#d8e9ed" font-family="Arial,sans-serif" font-size="10" letter-spacing="1">KNOWLEDGE MAP</text>${nodeMarkup}`
}

function renderVideoCover(resource, title) {
  const line = contentLines(resource, 1)[0] || escapeXml(title.slice(0, 22))
  return `<rect width="720" height="300" fill="#402f2e"/><path d="M0 0h720v300H0z" fill="#6d4940" opacity=".65"/><rect x="70" y="42" width="580" height="216" rx="10" fill="#241d1c"/><rect x="92" y="62" width="536" height="176" rx="5" fill="#2e555c"/><path d="M92 238l129-116 96 79 89-105 222 142z" fill="#729591"/><circle cx="360" cy="150" r="39" fill="#f7e7be"/><path d="M349 128l34 22-34 22z" fill="#7a473d"/><text x="104" y="278" fill="#f6dfc9" font-family="Arial,Microsoft YaHei,sans-serif" font-size="13" font-weight="700">${line}</text>`
}

export function generatedResourceCover(resource = {}) {
  const rawType = String(resource.resource_type || 'document').toLowerCase()
  const type = rawType === 'mind_map' || rawType === 'knowledge_map' ? 'mindmap' : rawType
  const title = String(resource.title || resource.topic || 'Learning resource').trim()
  const label = escapeXml(TYPE_LABELS[type] || 'LEARNING RESOURCE')
  const artwork = {
    document: renderDocumentCover,
    reading: renderDocumentCover,
    ppt: renderPptCover,
    mindmap: renderMindmapCover,
    video: renderVideoCover,
    external_video: renderVideoCover,
  }[type]?.(resource, title) || renderDocumentCover(resource, title)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="300" viewBox="0 0 720 300">${artwork}<rect x="18" y="18" width="${Math.max(86, label.length * 7 + 22)}" height="24" rx="12" fill="#1e3c34" fill-opacity=".88"/><text x="30" y="34" fill="#fff" font-family="Arial,sans-serif" font-size="10" font-weight="700" letter-spacing="1">${label}</text></svg>`
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`
}

function isGenericCover(value) {
  return /\/static\/covers\/default_[a-z_]+\.svg(?:[?#].*)?$/i.test(String(value || '').trim())
}

export function resourceCoverUrl(resource = {}) {
  const explicitValue = resource.cover_url || resource.thumbnail_url || resource.thumbnail
  const explicit = asHttpUrl(explicitValue)
  if (explicit && !isGenericCover(explicitValue)) return explicit

  const pageUrl = resource.page_url || resource.file_url || resource.url || ''
  const youtubeId = extractYouTubeId(pageUrl)
  if (youtubeId) return `https://i.ytimg.com/vi/${youtubeId}/hqdefault.jpg`

  // 视频封面必须来自后端或视频平台。没有真实封面时留空，不能用生成式占位图冒充真实视频画面。
  if (isVideoResource(resource)) return ''

  return generatedResourceCover(resource)
}

export function isVideoResource(resource = {}) {
  const type = String(resource.resource_type || resource.file_type || resource.type || '').toLowerCase()
  if (type === 'video' || type === 'external_video') return true
  const pageUrl = String(resource.page_url || resource.file_url || resource.url || '').toLowerCase()
  return /(?:bilibili\.com\/video\/|player\.bilibili\.com|(?:youtube\.com|youtu\.be)\/)/i.test(pageUrl)
}
