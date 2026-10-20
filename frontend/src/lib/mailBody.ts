import DOMPurify from 'dompurify'

/** Only trust the backend's body_type; never sniff content. */
export function isHtmlBody(bodyType?: string): boolean {
  return (bodyType || '').toLowerCase().includes('html')
}

/** Sanitize untrusted mail HTML. Scripts, event handlers and forms are removed. */
export function sanitizeMailHtml(html: string): string {
  return DOMPurify.sanitize(html || '', {
    WHOLE_DOCUMENT: false,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'textarea', 'select', 'base', 'meta', 'link'],
    FORBID_ATTR: ['srcset', 'formaction', 'action'],
    ALLOW_UNKNOWN_PROTOCOLS: false,
  })
}

export type MailSrcdocOptions = {
  /** When false, CSP blocks http(s) images (mail-core M5 default). Flask MessageReader keeps default true. */
  loadRemoteImages?: boolean
}

/**
 * Build the srcdoc for the sandboxed reader iframe. A strict CSP blocks scripts
 * even if sanitization ever misses something; links open in a new tab.
 * Flask default: loadRemoteImages=true (unchanged). mail-core readers should pass false.
 */
export function buildMailSrcdoc(html: string, opts: MailSrcdocOptions = {}): string {
  const loadRemote = opts.loadRemoteImages !== false
  const imgSrc = loadRemote ? "img-src https: http: data: cid:" : "img-src data: cid:"
  const csp = `default-src 'none'; ${imgSrc}; style-src 'unsafe-inline'; font-src https: data:`
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style>body{margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;word-wrap:break-word}img{max-width:100%;height:auto}</style></head><body>${sanitizeMailHtml(html)}</body></html>`
}

/** iframe sandbox flags: no allow-scripts, no allow-same-origin. */
export const MAIL_IFRAME_SANDBOX = 'allow-popups allow-popups-to-escape-sandbox'

/** Turn HTML into readable text for reply/forward quoting. */
export function htmlToText(html: string): string {
  const doc = new DOMParser().parseFromString(sanitizeMailHtml(html), 'text/html')
  doc.querySelectorAll('br').forEach((br) => br.replaceWith('\n'))
  doc.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,h5,h6').forEach((el) => el.append('\n'))
  return (doc.body.textContent || '').replace(/\n{3,}/g, '\n\n').trim()
}
