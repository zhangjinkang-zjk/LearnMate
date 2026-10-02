// 方案文档 —— 教练谈定一节就写一节，学生不用自己敲字。
//
// **为什么按节合并，而不是整篇重写**：教练每次只带回来一节。让它每次重写整篇，
// 越往后越容易把前面谈好的节漏掉（它得把整场对话的结论一次性复述完整），而漏掉是
// 无声的 —— 学生打开只看到少了一段，不知道是被覆盖了。按节合并时，没提到的那几节
// 原样不动，最坏情况只是这一节没更新。

export const DESIGN_DOC_PATH = 'docs/方案.md'

// 文档新建时的 H1。没有它的话文档第一行就是 `## 技术栈`，看着像个片段而不是一份文档。
const DOC_TITLE = '# 方案'

const SECTION_HEADING = /^##\s+/

/**
 * 把一节并进文档正文。
 *
 * 有同名 `## 标题` 就换掉那一节的正文（到下一个 `##` 为止），没有就追加到末尾。
 * 返回新正文，**不改入参**。
 */
export function mergeDocSection(text, section, content) {
  const heading = `## ${String(section ?? '').trim()}`
  const body = String(content ?? '').trim()
  const source = String(text ?? '')

  const lines = source.split('\n')
  const start = lines.findIndex((line) => line.trim() === heading)

  if (start === -1) {
    const head = source.trim() ? `${source.replace(/\s+$/, '')}\n\n` : `${DOC_TITLE}\n\n`
    return `${head}${heading}\n\n${body}\n`
  }

  // 这一节的结束位置 = 下一个二级标题（`##`）之前。更深的标题（`###`）属于本节内容，
  // 所以只认 `##` 开头，不能拿 `/^#/` 一把抓 —— 那会把子标题当成下一节的开头切掉。
  let end = lines.length
  for (let i = start + 1; i < lines.length; i += 1) {
    if (SECTION_HEADING.test(lines[i])) { end = i; break }
  }

  const merged = [...lines.slice(0, start), heading, '', body, '', ...lines.slice(end)]
  return `${merged.join('\n').replace(/\n{3,}/g, '\n\n').replace(/\s+$/, '')}\n`
}
