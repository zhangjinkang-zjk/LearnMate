export const visibilityLabels = { pending: '待审核', public: '已公开', private: '私有', rejected: '已驳回' }
export function formatDate(value) {
  if (!value) return '尚无记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '尚无记录' : date.toLocaleString('zh-CN', { hour12: false })
}
export function formatDuration(seconds) {
  const minutes = Math.floor((Number(seconds) || 0) / 60)
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` : `${minutes} 分钟`
}
