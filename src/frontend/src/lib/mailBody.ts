import DOMPurify from 'dompurify'

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/** Only trust the backend's body_type; never sniff content. */
export function isHtmlBody(bodyType?: string): boolean {
  return (bodyType || '').toLowerCase().includes('html')
}

/** Sanitize untrusted mail HTML. Scripts, event handlers and forms are removed. */
export function sanitizeMailHtml(html: string): string {
  return DOMPurify.sanitize(html || '', {
    USE_PROFILES: { html: true },
    WHOLE_DOCUMENT: false,
    FORBID_TAGS: [
      'script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'button',
      'textarea', 'select', 'base', 'meta', 'link', 'svg', 'math', 'video',
      'audio', 'source', 'track', 'details',
    ],
    FORBID_ATTR: ['srcset', 'formaction', 'action', 'ping', 'background'],
    ALLOW_UNKNOWN_PROTOCOLS: false,
  })
}

export type MailHtmlClassification = 'plain' | 'light' | 'dark'

export type PreparedMailHtml = {
  sanitizedHtml: string
  classification: MailHtmlClassification
}

export type InlineAttachmentCandidate = {
  content_id?: string | null
  preview_url?: string | null
  is_inline?: boolean
}

export type RemoteImageMapping = {
  url: string
  proxy_url: string
}

/**
 * Normalize a MIME header Content-ID according to RFC 2392 / RFC 2045:
 * Strips enclosing angle brackets and whitespace, converts to lowercase.
 * Does NOT perform unconstrained percent-decoding (literal Content-ID semantics).
 * Rejects IDs exceeding 255 characters or empty IDs.
 */
export function normalizeHeaderContentId(rawId: string | null | undefined): string | null {
  if (!rawId) return null
  let s = rawId.trim()
  if (s.startsWith('<') && s.endsWith('>')) {
    s = s.slice(1, -1).trim()
  }
  if (!s || s.length > 255) return null
  return s.toLowerCase()
}

/**
 * Normalize a CID URL reference from HTML (<img src="cid:...">):
 * Strips 'cid:' scheme, decodes URI percent-encoding strictly once, strips angle brackets/whitespace, converts to lowercase.
 * Rejects malformed percent-encoding, IDs exceeding 255 characters, or empty IDs.
 */
export function normalizeCidUrl(rawUrl: string | null | undefined): string | null {
  if (!rawUrl) return null
  let s = rawUrl.trim()
  if (!s.toLowerCase().startsWith('cid:')) return null
  s = s.slice(4).trim()
  if (s.startsWith('<') && s.endsWith('>')) {
    s = s.slice(1, -1).trim()
  }
  try {
    s = decodeURIComponent(s)
  } catch {
    // Malformed percent-encoding (e.g. cid:% or invalid escape) -> fail-safe fallback
    return null
  }
  if (s.startsWith('<') && s.endsWith('>')) {
    s = s.slice(1, -1).trim()
  }
  if (!s || s.length > 255) return null
  return s.toLowerCase()
}

/** Compatibility helper maintaining normalizeCid signature for test suite. */
export function normalizeCid(rawCid: string | null | undefined): string {
  if (!rawCid) return ''
  return (rawCid.trim().toLowerCase().startsWith('cid:') ? normalizeCidUrl(rawCid) : normalizeHeaderContentId(rawCid)) ?? ''
}

/**
 * Rewrite <img src="cid:..."> in mail HTML to short-lived Signed URLs before sanitization.
 * Operates in an offline DOM container using attribute APIs.
 */
export function rewriteCidImages(
  html: string,
  attachments?: InlineAttachmentCandidate[],
): string {
  if (!html || !attachments || attachments.length === 0) {
    return html || ''
  }

  // 1. Identify all normalized CIDs across candidates and detect conflicts
  const cidMap = new Map<string, string>()
  const conflicted = new Set<string>()

  for (const att of attachments) {
    if (att.is_inline === false) continue
    const norm = normalizeHeaderContentId(att.content_id)
    if (!norm) continue
    if (cidMap.has(norm)) {
      // Conflict: multiple attachments share the same normalized Content-ID
      conflicted.add(norm)
    } else if (att.preview_url) {
      cidMap.set(norm, att.preview_url)
    } else {
      // Attachment has a CID but no preview_url (e.g. non-image inline part)
      cidMap.set(norm, '')
    }
  }

  for (const conf of conflicted) {
    cidMap.delete(conf)
  }

  if (cidMap.size === 0) {
    return html
  }

  const doc = new DOMParser().parseFromString(html, 'text/html')
  const images = doc.querySelectorAll('img')
  let modified = false

  for (const img of Array.from(images)) {
    const src = img.getAttribute('src') || ''
    const norm = normalizeCidUrl(src)
    if (norm) {
      const previewUrl = cidMap.get(norm)
      if (previewUrl) {
        img.setAttribute('src', previewUrl)
        modified = true
      }
    }
  }

  if (!modified) {
    return html
  }

  return doc.body ? doc.body.innerHTML : html
}

/**
 * Normalize a remote image URL exactly like the backend extractor:
 * trim, resolve protocol-relative URLs to https, reject non-http(s).
 */
export function normalizeRemoteImageUrl(raw: string | null | undefined): string | null {
  if (!raw) return null
  let url = raw.trim()
  if (!url) return null
  if (url.startsWith('//')) url = `https:${url}`
  if (!/^https?:\/\//i.test(url)) return null
  return url
}

/**
 * Rewrite external remote image URLs (in <img src="..."> and inline style background-image)
 * to internal safe proxy URLs.
 */
export function rewriteRemoteImages(
  html: string,
  remoteImages?: RemoteImageMapping[],
): string {
  if (!html || !remoteImages || remoteImages.length === 0) {
    return html || ''
  }

  const mapping = new Map<string, string>()
  for (const item of remoteImages) {
    const key = normalizeRemoteImageUrl(item.url)
    if (key && item.proxy_url) {
      mapping.set(key, item.proxy_url)
    }
  }

  if (mapping.size === 0) {
    return html
  }

  const doc = new DOMParser().parseFromString(html, 'text/html')
  let modified = false

  // 1. Rewrite <img src="...">
  const images = doc.querySelectorAll('img')
  for (const img of Array.from(images)) {
    const src = normalizeRemoteImageUrl(img.getAttribute('src'))
    if (src && mapping.has(src)) {
      img.setAttribute('src', mapping.get(src)!)
      modified = true
    }
  }

  // 2. Rewrite inline background-image styles
  const bgUrlPattern = /url\(\s*(['"]?)([^'")>\s]+)\1\s*\)/gi
  const styledEls = doc.querySelectorAll('*[style]')
  for (const el of Array.from(styledEls)) {
    const style = el.getAttribute('style') || ''
    if (/url\(/i.test(style)) {
      let changed = false
      const newStyle = style.replace(bgUrlPattern, (match, _quote, url) => {
        const normalized = normalizeRemoteImageUrl(url)
        if (normalized && mapping.has(normalized)) {
          changed = true
          return `url("${mapping.get(normalized)!}")`
        }
        return match
      })
      if (changed) {
        el.setAttribute('style', newStyle)
        modified = true
      }
    }
  }

  if (!modified) {
    return html
  }

  return doc.body ? doc.body.innerHTML : html
}

/**
 * Detect whether the sanitized HTML contains external remote images (http:, https:, //).
 * Checks both <img src="..."> and inline style background-image URLs.
 * Does not count data:, /api/mail/... preview or proxy URLs, or cid: placeholders.
 */
export function hasRemoteImages(sanitizedHtml: string): boolean {
  if (!sanitizedHtml) return false
  const doc = new DOMParser().parseFromString(sanitizedHtml, 'text/html')
  const images = doc.querySelectorAll('img')
  for (const img of Array.from(images)) {
    const src = (img.getAttribute('src') || '').trim()
    if (/^(?:https?:|\/\/)/i.test(src)) {
      return true
    }
  }
  const styledEls = doc.querySelectorAll('*[style]')
  for (const el of Array.from(styledEls)) {
    const style = el.getAttribute('style') || ''
    if (/url\(\s*['"]?(?:https?:|\/\/)/i.test(style)) {
      return true
    }
  }
  return false
}

function parseColorBrightness(colorStr: string): 'light' | 'dark' | null {
  const s = colorStr.trim().toLowerCase()
  if (['white', '#fff', '#ffffff', '#fafafa', '#f8f9fa', '#f5f5f5', '#eeeeee', '#e0e0e0'].includes(s)) {
    return 'light'
  }
  if (['black', '#000', '#000000', '#111', '#1a1a1c', '#222729', '#222', '#333'].includes(s)) {
    return 'dark'
  }
  const hex3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s)
  if (hex3) {
    const r = parseInt(hex3[1] + hex3[1], 16)
    const g = parseInt(hex3[2] + hex3[2], 16)
    const b = parseInt(hex3[3] + hex3[3], 16)
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return lum > 0.6 ? 'light' : 'dark'
  }
  const hex6 = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(s)
  if (hex6) {
    const r = parseInt(hex6[1], 16)
    const g = parseInt(hex6[2], 16)
    const b = parseInt(hex6[3], 16)
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return lum > 0.6 ? 'light' : 'dark'
  }
  const rgb = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(s)
  if (rgb) {
    const r = parseInt(rgb[1], 10)
    const g = parseInt(rgb[2], 10)
    const b = parseInt(rgb[3], 10)
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return lum > 0.6 ? 'light' : 'dark'
  }
  return null
}

/**
 * Classify HTML content into 'plain' (unstyled), 'light' (explicit fixed light), or 'dark' (explicit dark).
 * Conservative approach: only treat as 'light' if explicit light background/bgcolor is present.
 */
function classifySanitizedMailHtml(sanitized: string): MailHtmlClassification {
  if (!sanitized) return 'plain'
  if (!/bgcolor|background|color/i.test(sanitized)) {
    return 'plain'
  }

  const doc = new DOMParser().parseFromString(sanitized, 'text/html')
  const elements = doc.querySelectorAll('*')

  let hasExplicitLight = false
  let hasExplicitDark = false

  for (const el of Array.from(elements)) {
    const bgcolor = el.getAttribute('bgcolor')
    if (bgcolor) {
      const b = parseColorBrightness(bgcolor)
      if (b === 'light') hasExplicitLight = true
      if (b === 'dark') hasExplicitDark = true
    }
    const style = el.getAttribute('style') || ''
    if (style) {
      const bgMatch = /background(?:-color)?\s*:\s*([^;!]+)/i.exec(style)
      if (bgMatch) {
        const b = parseColorBrightness(bgMatch[1])
        if (b === 'light') hasExplicitLight = true
        if (b === 'dark') hasExplicitDark = true
      }
    }
  }

  if (hasExplicitLight) return 'light'
  if (hasExplicitDark) return 'dark'
  return 'plain'
}

/** Sanitize HTML once and reuse it for classification and srcdoc generation. */
export function prepareMailHtml(
  html: string,
  attachments?: InlineAttachmentCandidate[],
  remoteImages?: RemoteImageMapping[],
): PreparedMailHtml {
  let rewritten = rewriteCidImages(html, attachments)
  if (remoteImages && remoteImages.length > 0) {
    rewritten = rewriteRemoteImages(rewritten, remoteImages)
  }
  const sanitizedHtml = sanitizeMailHtml(rewritten)
  return {
    sanitizedHtml,
    classification: classifySanitizedMailHtml(sanitizedHtml),
  }
}

export function classifyMailHtml(
  html: string,
  attachments?: InlineAttachmentCandidate[],
  remoteImages?: RemoteImageMapping[],
): MailHtmlClassification {
  if (!html || typeof html !== 'string') return 'plain'
  return prepareMailHtml(html, attachments, remoteImages).classification
}

export type MailSrcdocOptions = {
  /** Remote http(s) images are blocked unless explicitly true (privacy default). */
  loadRemoteImages?: boolean
  /** Active theme: 'light' or 'dark' */
  theme?: 'light' | 'dark'
  /** Classification computed from the same sanitized HTML, when already available. */
  classification?: MailHtmlClassification
  /** Sanitized HTML and its classification prepared for reuse. */
  preparedHtml?: PreparedMailHtml
  /**
   * Whether to apply smart inversion in dark mode for light HTML mails.
   * Defaults to true when theme === 'dark' and classification === 'light'.
   */
  darkModeInvert?: boolean
}

/**
 * Build the srcdoc for the sandboxed reader iframe. A strict CSP blocks scripts
 * even if sanitization ever misses something; links open in a new tab.
 *
 * Remote images are securely proxied through the kkmail origin, so img-src permanently
 * stays locked to 'self' data: cid: with zero external network leakage.
 */
export function buildMailSrcdoc(html: string, opts: MailSrcdocOptions = {}): string {
  const csp = "default-src 'none'; img-src 'self' data: cid:; style-src 'unsafe-inline'; font-src data:"

  const theme = opts.theme || 'light'
  const sanitizedHtml = opts.preparedHtml?.sanitizedHtml ?? sanitizeMailHtml(html)
  const classification = opts.classification ?? opts.preparedHtml?.classification ?? classifySanitizedMailHtml(sanitizedHtml)

  const isDark = theme === 'dark'
  const isLightClass = classification === 'light'
  const shouldInvert = isDark && isLightClass && opts.darkModeInvert !== false

  const isDarkPlain = isDark && !shouldInvert && classification !== 'light'
  const bg = isDarkPlain ? '#222729' : '#ffffff'
  const text = isDarkPlain ? '#FFFFFF' : '#202124'
  const linkColor = isDarkPlain ? '#0A84FF' : '#0066CC'

  const bodyStyle = `margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;word-wrap:break-word;background:${bg};color:${text}`
  const linkStyle = `a{color:${linkColor}}`
  const imgStyle = `img{max-width:100%;height:auto}`
  const invertStyle = shouldInvert
    ? 'html{filter:invert(100%) hue-rotate(180deg);background:#ffffff}img,video,canvas{filter:invert(100%) hue-rotate(180deg) drop-shadow(0 0 1px rgba(0, 0, 0, 0.75))}'
    : ''

  const colorScheme = isDark ? 'dark' : 'light'
  const scrollbarStyle = isDark
    ? ':root{color-scheme:dark}html{scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.28) transparent}::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.28);border-radius:4px}::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.45)}'
    : ':root{color-scheme:light}html{scrollbar-width:thin;scrollbar-color:rgba(0,0,0,0.28) transparent}::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(0,0,0,0.28);border-radius:4px}::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,0.45)}'

  return `<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta name="color-scheme" content="${colorScheme}"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank" rel="noopener noreferrer"><style>${scrollbarStyle}${invertStyle}body{${bodyStyle}}${linkStyle}${imgStyle}</style></head><body>${sanitizedHtml}</body></html>`
}

/**
 * iframe sandbox flags for the mail reader — threat-model adjudication
 * (A384, decision: option A, KEEP `allow-popups-to-escape-sandbox`).
 *
 * Why the escape flag stays: mail links are forced to target="_blank"
 * (the DOMPurify hook in this module and the srcdoc <base> tag). A popup opened
 * from a sandboxed iframe without the escape flag inherits the sandbox:
 * the destination site would run with scripts disabled and an opaque
 * origin, which breaks the normal web functionality of legitimate links
 * in mail (the entire point of letting the user open them). With the
 * escape flag, the popup is an ordinary new browsing context — exactly
 * equivalent to the user opening that link in any other mail client.
 *
 * What the escaped popup does NOT get, i.e. the accepted-risk boundary:
 * - No access to kkmail itself. The iframe deliberately has neither
 *   `allow-scripts` nor `allow-same-origin`, so mail content runs no
 *   script at all inside kkmail and the srcdoc document has an opaque
 *   origin; there is no scriptable path from the mail body to the app,
 *   its DOM, its storage, or its session.
 * - No opener handle. Every sanitized anchor is forced to
 *   rel="noopener noreferrer" (afterSanitizeAttributes hook), the
 *   srcdoc repeats that on <base>, and referrerPolicy/meta no-referrer
 *   suppresses referrer leakage, so the popup cannot reach
 *   window.opener or learn the app URL.
 * - No dangerous navigation created by content. DOMPurify strips
 *   scripts, event handlers, forms and unknown protocols
 *   (ALLOW_UNKNOWN_PROTOCOLS: false), so only a genuine user click on
 *   a sanitized http(s)-style link can open a popup; mail content
 *   cannot spawn popups by itself.
 *
 * Invariants that must NOT change without re-adjudicating this
 * decision: never add `allow-scripts` or `allow-same-origin` to this
 * sandbox (together they would let content remove its own sandbox and
 * script the parent), never drop the noopener/noreferrer enforcement,
 * and never weaken the sanitizer's protocol filtering. The residual
 * risk consciously accepted is only this: a user who clicks a hostile
 * link lands on a hostile *external* page — the same risk as any link
 * click in a browser — with no kkmail privileges attached.
 */
export const MAIL_IFRAME_SANDBOX = 'allow-popups allow-popups-to-escape-sandbox'
