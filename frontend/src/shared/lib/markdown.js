import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false,
})

const defaultLinkOpen = markdown.renderer.rules.link_open
  || ((tokens, index, options, _env, renderer) => renderer.renderToken(tokens, index, options))

markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, index, options, env, renderer)
}

export function renderMarkdown(source) {
  const normalizedSource = String(source || '')
    .replace(/(\*\*[^*\n]+?\*\*)(?=[\u3400-\u9fff])/g, '$1 ')
  return DOMPurify.sanitize(markdown.render(normalizedSource), {
    USE_PROFILES: { html: true },
  })
}
