import httpClient from './httpClient'

/** Only backend static assets and explicit HTTP(S) URLs may become file links. */
export function resolveResourceFileUrl(value) {
  const url = String(value || '').trim()
  if (/^https?:\/\//i.test(url)) return url
  if (!url.startsWith('/static/')) return ''
  try { return new URL(url, httpClient.defaults.baseURL || window.location.origin).href }
  catch { return '' }
}
