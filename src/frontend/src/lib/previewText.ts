/** Strip HTML tags and collapse whitespace for list previews. */
function decodeNumericEntity(_match: string, hex?: string, decimal?: string): string {
  const codePoint = Number.parseInt(hex ?? decimal ?? '', hex ? 16 : 10)
  const isSurrogate = codePoint >= 0xd800 && codePoint <= 0xdfff
  if (!Number.isInteger(codePoint) || codePoint <= 0 || codePoint > 0x10ffff || isSurrogate) return '\uFFFD'
  return String.fromCodePoint(codePoint)
}

export function stripHtmlToText(html: string): string {
  let text = html.replace(/<!--[\s\S]*?(?:-->|$)|<!doctype\b[^>]*(?:>|$)/gi, ' ')
  text = text.replace(/<(head|script|style)\b[\s\S]*?(?:<\/\1>|$)/gi, ' ')
  text = text.replace(/<br\s*\/?>/gi, '\n')
  text = text.replace(/<\/(p|div|li|tr|h[1-6])>/gi, '\n')
  text = text.replace(/<\/?[a-z][a-z0-9]*(?:\s[^<>]*|\s*\/?)>/gi, ' ')
  text = text.replace(/<\/?(?:html|head|body|meta|div|p|span|table|br|a|img)(?=[\s/]|$)[^>]*$/gi, ' ')
  text = text
    .replace(/&#(?:x([0-9a-f]+)|(\d+));/gi, decodeNumericEntity)
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
  return text.replace(/\s+/g, ' ').trim()
}

function looksLikeHtml(src: string): boolean {
  return /<\/?[a-z][a-z0-9]*(?:\s[^<>]*|\s*\/?)>/i.test(src)
    || /&[a-z]+;/i.test(src)
    || /&#(?:\d+|x[0-9a-f]+);/i.test(src)
    || src.startsWith('<!')
}

/** Turn a body_preview (which may still contain HTML) into plain list text. */
export function previewText(raw?: string, max = 180): string {
  const src = (raw || '').trim()
  if (!src) return ''
  // Bound the input before the multi-pass regex strip: body text is
  // attacker-controlled and can be arbitrarily long, while the preview only
  // ever shows `max` chars. Capping at 4×max leaves headroom for tags and
  // entities; the tradeoff is that markup/entity-dense heads may yield a
  // shorter preview, which is acceptable for a list snippet.
  const bounded = src.length > max * 4 ? src.slice(0, max * 4) : src
  const plain = (looksLikeHtml(bounded) ? stripHtmlToText(bounded) : bounded).replace(/\s+/g, ' ').trim()
  if (plain.length <= max) return plain
  return `${plain.slice(0, max).trimEnd()}…`
}
