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
    FORBID_ATTR: ['srcset', 'formaction', 'action'],
    ALLOW_UNKNOWN_PROTOCOLS: false,
  })
}

export type MailHtmlClassification = 'plain' | 'light' | 'dark'

export type PreparedMailHtml = {
  sanitizedHtml: string
  classification: MailHtmlClassification
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
export function prepareMailHtml(html: string): PreparedMailHtml {
  const sanitizedHtml = sanitizeMailHtml(html)
  return {
    sanitizedHtml,
    classification: classifySanitizedMailHtml(sanitizedHtml),
  }
}

export function classifyMailHtml(html: string): MailHtmlClassification {
  if (!html || typeof html !== 'string') return 'plain'
  return prepareMailHtml(html).classification
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
}

/**
 * Build the srcdoc for the sandboxed reader iframe. A strict CSP blocks scripts
 * even if sanitization ever misses something; links open in a new tab.
 * Remote images are off by default.
 */
export function buildMailSrcdoc(html: string, opts: MailSrcdocOptions = {}): string {
  const loadRemote = opts.loadRemoteImages === true
  const imgSrc = loadRemote ? 'img-src https: http: data: cid:' : 'img-src data: cid:'
  const csp = `default-src 'none'; ${imgSrc}; style-src 'unsafe-inline'; font-src https: data:`

  const theme = opts.theme || 'light'
  const sanitizedHtml = opts.preparedHtml?.sanitizedHtml ?? sanitizeMailHtml(html)
  const classification = opts.classification ?? opts.preparedHtml?.classification ?? classifySanitizedMailHtml(sanitizedHtml)

  const isDarkPlain = theme === 'dark' && classification !== 'light'
  const bg = isDarkPlain ? '#222729' : '#ffffff'
  const text = isDarkPlain ? '#FFFFFF' : '#202124'
  const linkColor = isDarkPlain ? '#0A84FF' : '#0066CC'

  const bodyStyle = `margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;word-wrap:break-word;background:${bg};color:${text}`
  const linkStyle = `a{color:${linkColor}}`
  const imgStyle = `img{max-width:100%;height:auto}`

  return `<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank" rel="noopener noreferrer"><style>body{${bodyStyle}}${linkStyle}${imgStyle}</style></head><body>${sanitizedHtml}</body></html>`
}

/** iframe sandbox flags: allow-popups and allow-popups-to-escape-sandbox for opening links in new windows. */
export const MAIL_IFRAME_SANDBOX = 'allow-popups allow-popups-to-escape-sandbox'
