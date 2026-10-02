export const visibilityLabels = { pending: '待审核', public: '已公开', private: '私有', rejected: '已驳回' }
const resourceTypes = { document: '学习文档', ppt: '演示课件', mindmap: '思维导图', exercise: '练习题', case: '案例', reading: '拓展阅读', slide_animation: '动画课件', audio: '音频', html: '交互材料', video: '视频', external_video: '外部视频', image: '图片' }
export function formatResourceType(value) { return resourceTypes[value] || '学习资源' }
export function formatDate(value) {
  if (!value) return '尚无记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '尚无记录' : date.toLocaleString('zh-CN', { hour12: false })
}
export function formatDuration(seconds) {
  const minutes = Math.floor((Number(seconds) || 0) / 60)
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` : `${minutes} 分钟`
}
