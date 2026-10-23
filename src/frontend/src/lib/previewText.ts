/** Strip HTML tags and collapse whitespace for list previews. */
export function stripHtmlToText(html: string): string {
  let text = html.replace(/<!--[\s\S]*?(?:-->|$)|<!doctype\b[^>]*(?:>|$)/gi, ' ')
  text = text.replace(/<(head|script|style)\b[\s\S]*?(?:<\/\1>|$)/gi, ' ')
  text = text.replace(/<br\s*\/?>/gi, '\n')
  text = text.replace(/<\/(p|div|li|tr|h[1-6])>/gi, '\n')
  text = text.replace(/<\/?[a-z][a-z0-9]*(?:\s[^<>]*|\s*\/?)>/gi, ' ')
  text = text.replace(/<\/?(?:html|head|body|meta|div|p|span|table|br|a|img)(?=[\s/]|$)[^>]*$/gi, ' ')
  text = text
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
  return text.replace(/\s+/g, ' ').trim()
}

function looksLikeHtml(src: string): boolean {
  return /<\/?[a-z][a-z0-9]*(?:\s[^<>]*|\s*\/?)>/i.test(src) || /&[a-z]+;/i.test(src) || src.startsWith('<!')
}

/** Turn a body_preview (which may still contain HTML) into plain list text. */
export function previewText(raw?: string, max = 180): string {
  const src = (raw || '').trim()
  if (!src) return ''
  const plain = (looksLikeHtml(src) ? stripHtmlToText(src) : src).replace(/\s+/g, ' ').trim()
  if (plain.length <= max) return plain
  return `${plain.slice(0, max).trimEnd()}…`
}
