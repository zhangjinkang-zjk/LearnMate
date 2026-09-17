import httpClient from './httpClient'

// 上传/修改是 multipart，而 httpClient 的默认头是 application/json。
// axios 的 transformRequest 看到「FormData + JSON 头」会走 formDataToJSON 分支，
// 把整个 FormData **转成 JSON 字符串**发出去（axios/lib/defaults/index.js:53-56）——
// 请求返回 200，后端却一个字段也收不到，而且不报错，极难查。
// 所以每次都要显式改掉这个头：改成 multipart/form-data 之后，axios 会在
// resolveConfig 里把它置空（helpers/resolveConfig.js:72-74），由浏览器自己带上 boundary。
// **不要顺手删掉这行 header，也不要把它挪到 httpClient 的默认头里。**
const MULTIPART_HEADERS = { 'Content-Type': 'multipart/form-data' }

// 上传这一下要做完：落盘 → 抽文本 → 切片 → 逐段算向量入库。
// 全局 15 秒超时不够（知伴那边整个实例给到 5 分钟），这里单独给 5 分钟。
const UPLOAD_TIMEOUT_MS = 300000

// 与后端 knowledge_router.ALLOWED_EXTENSIONS 逐项一致（有测试钉着）。
// 视频没有本地首帧封面，封面是可选参数，不传即可。
export const KNOWLEDGE_ACCEPT = '.txt,.md,.csv,.json,.pdf,.docx,.mp4'

// 可以在本地读成文字做预览的后缀：其余（pdf/docx/mp4）只能交给后端解析。
export const TEXT_PREVIEW_EXTENSIONS = ['txt', 'md', 'csv', 'json']

// 资料类型。后端 category 是自由字符串（默认 knowledge_point），这六个值只是约定，
// 但默认值必须落在列表里，否则"默认类型"在前端根本选不中。
export const knowledgeCategoryOptions = [
  { value: 'knowledge_point', label: '知识点讲解' },
  { value: 'exercise', label: '习题/题库' },
  { value: 'textbook', label: '教科书章节' },
  { value: 'note', label: '学习笔记' },
  { value: 'case_study', label: '实操案例' },
  { value: 'reference', label: '参考资料' },
]

export const knowledgeCategoryLabel = (value) =>
  knowledgeCategoryOptions.find((item) => item.value === value)?.label || '学习资料'

export const visibilityLabel = (value) => ({
  private: '仅我可见',
  public: '全员可见',
  pending: '待管理员审核',
}[value] || '仅我可见')

export const knowledgeApi = {
  // formData 字段名必须和后端 upload_document 的 Form 参数一致：file / title / visibility / category
  upload: (formData, onUploadProgress) => httpClient.post('/knowledge_base/upload', formData, {
    headers: MULTIPART_HEADERS,
    timeout: UPLOAD_TIMEOUT_MS,
    onUploadProgress,
  }),
  // mine=true 时后端只看自己的（公开的仍会出现）
  list: (params = {}) => httpClient.get('/knowledge_base/list', { params }),
  // 删除是**按单条切片**删的（后端 delete 一次只删一行）：一篇文档切成 N 段，
  // 就要删 N 次，少删一次列表里会剩下半篇。
  remove: (docId) => httpClient.delete(`/knowledge_base/${encodeURIComponent(docId)}`),
  removeAll: async (docIds = []) => {
    const results = []
    for (const docId of docIds) {
      results.push(await knowledgeApi.remove(docId))
    }
    return results
  },
}
