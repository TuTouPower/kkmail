// @vitest-environment jsdom
import DOMPurify from 'dompurify'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  MAIL_IFRAME_SANDBOX,
  buildMailSrcdoc,
  classifyMailHtml,
  hasRemoteImages,
  isHtmlBody,
  normalizeCidUrl,
  normalizeHeaderContentId,
  prepareMailHtml,
  rewriteCidImages,
  sanitizeMailHtml,
} from './mailBody'

afterEach(() => vi.restoreAllMocks())

describe('mail body safety and dark mode classification (AC-003)', () => {
  it('strips event handlers and scripts', () => {
    const out = sanitizeMailHtml('<p>hi</p><img src=x onerror=alert(1)><script>alert(2)</script><a href="javascript:alert(3)">x</a>')
    expect(out).not.toMatch(/onerror/i)
    expect(out).not.toMatch(/<script/i)
    expect(out).not.toMatch(/javascript:/i)
    expect(out).toContain('<p>hi</p>')
  })

  it('removes iframes, forms and svg handlers', () => {
    const out = sanitizeMailHtml('<iframe src="https://evil"></iframe><form action="/x"><input></form><svg onload=alert(1)></svg>')
    expect(out).not.toMatch(/<iframe|<form|<input|onload/i)
  })

  it('removes forbidden multimedia and active tags (svg, math, video, audio, details)', () => {
    const out = sanitizeMailHtml(
      '<svg><circle /></svg><math><mi>x</mi></math><video src="v.mp4"><source src="v.mp4"><track></video><audio src="a.mp3"></audio><details><summary>s</summary>d</details>',
    )
    expect(out).not.toMatch(/<svg|<math|<video|<audio|<source|<track|<details/i)
  })

  // t066: The CSP image source directive uses standard 'self' keyword to permit
  // local signed preview endpoints and data: while blocking remote images.
  it('wraps output in a CSP document with rel="noopener noreferrer" base, no-referrer meta, and preview endpoint', () => {
    const doc = buildMailSrcdoc('<img src=x onerror=alert(1)>')
    expect(doc).toContain("default-src 'none'")
    expect(doc).toContain("img-src 'self' data: cid:")
    expect(doc).toContain('<meta name="referrer" content="no-referrer">')
    expect(doc).toContain('<base target="_blank" rel="noopener noreferrer">')
    expect(doc).not.toMatch(/onerror/i)
  })

  it('removes link ping beacons and background URL attributes', () => {
    const out = sanitizeMailHtml(
      '<a href="https://example.com" ping="https://tracker.example/ping">link</a>' +
        '<table background="https://tracker.example/bg"><tr><td>mail</td></tr></table>',
    )
    expect(out).not.toMatch(/\sping=/i)
    expect(out).not.toMatch(/\sbackground=/i)
    expect(out).toContain('link')
    expect(out).toContain('mail')
  })

  it('enforces rel="noopener noreferrer" and target="_blank" on anchor tags', () => {
    const out = sanitizeMailHtml('<a href="https://example.com">link</a>')
    expect(out).toContain('target="_blank"')
    expect(out).toContain('rel="noopener noreferrer"')
  })

  // t068: In accordance with d003 and t068 specs, the iframe CSP permanently stays
  // locked to 'self' data: cid: (zero external network leakage). External remote images
  // are rewritten to the kkmail backend proxy endpoint (/api/mail/messages/.../remote-images).
  it('permanently locks iframe CSP to self data cid and rewrites remote images to proxy endpoints', () => {
    const rawHtml = '<p>Check photo</p><img src="https://tracker.test/pixel.png">'
    // 1. By default, CSP is locked and no external origin is allowed
    const defaultDoc = buildMailSrcdoc(rawHtml)
    expect(defaultDoc).toContain("img-src 'self' data: cid:")
    expect(defaultDoc).not.toContain('img-src https:')
    expect(defaultDoc).not.toContain("img-src 'self' https:")

    // 2. Even when loadRemoteImages is requested, CSP remains locked to self
    const optInDoc = buildMailSrcdoc(rawHtml, { loadRemoteImages: true })
    expect(optInDoc).toContain("img-src 'self' data: cid:")
    expect(optInDoc).not.toContain('img-src https:')
    expect(optInDoc).not.toContain("img-src 'self' https:")

    // 3. rewriteRemoteImages replaces external img src and style background-image
    const prepared = prepareMailHtml(
      '<p>Body</p><img src="https://tracker.test/pixel.png"><div style="background-image: url(\'https://tracker.test/bg.jpg\')"></div>',
      undefined,
      [
        { url: 'https://tracker.test/pixel.png', proxy_url: '/api/mail/messages/m-1/remote-images?url=pixel&token=123' },
        { url: 'https://tracker.test/bg.jpg', proxy_url: '/api/mail/messages/m-1/remote-images?url=bg&token=456' },
      ],
    )
    expect(prepared.sanitizedHtml).toContain('src="/api/mail/messages/m-1/remote-images?url=pixel&amp;token=123"')
    expect(prepared.sanitizedHtml).toContain('/api/mail/messages/m-1/remote-images?url=bg&amp;token=456')
    expect(prepared.sanitizedHtml).not.toContain('https://tracker.test/pixel.png')
    expect(prepared.sanitizedHtml).not.toContain('https://tracker.test/bg.jpg')
  })

  it('locks the A384 popup-escape adjudication boundaries: exact sandbox, no opener, protocol filtering intact', () => {
    // Option A keeps the escape flag — the constant is pinned exactly so
    // nobody can silently add allow-scripts / allow-same-origin /
    // allow-top-navigation, any of which would void the adjudication
    // recorded above MAIL_IFRAME_SANDBOX in mailBody.ts.
    expect(MAIL_IFRAME_SANDBOX).toBe('allow-popups allow-popups-to-escape-sandbox')
    // The popup must not get an opener handle or a referrer.
    const out = sanitizeMailHtml('<a href="https://example.com">link</a>')
    expect(out).toContain('target="_blank"')
    expect(out).toContain('rel="noopener noreferrer"')
    const doc = buildMailSrcdoc('<a href="https://example.com">link</a>')
    expect(doc).toContain('<base target="_blank" rel="noopener noreferrer">')
    expect(doc).toContain('<meta name="referrer" content="no-referrer">')
    expect(doc).toContain("default-src 'none'")
    // Protocol filtering is part of the boundary: non-web schemes in
    // links must never survive sanitization into a clickable popup.
    expect(sanitizeMailHtml('<a href="javascript:alert(1)">x</a>')).not.toMatch(/javascript:/i)
    expect(sanitizeMailHtml('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>')).not.toMatch(/data:text\/html/i)
  })

  it('sandbox allows popups and escaping sandbox, but never scripts or same-origin', () => {
    expect(MAIL_IFRAME_SANDBOX).not.toContain('allow-scripts')
    expect(MAIL_IFRAME_SANDBOX).not.toContain('allow-same-origin')
    expect(MAIL_IFRAME_SANDBOX).toContain('allow-popups')
    expect(MAIL_IFRAME_SANDBOX).toContain('allow-popups-to-escape-sandbox')
  })

  it('detects html only from body_type', () => {
    expect(isHtmlBody('html')).toBe(true)
    expect(isHtmlBody('text/HTML')).toBe(true)
    expect(isHtmlBody('text')).toBe(false)
    expect(isHtmlBody(undefined)).toBe(false)
  })

  it('classifies unstyled html as plain and applies dark body #222729 and text #FFFFFF in dark mode (AC-003)', () => {
    const plainHtml = '<p>Simple paragraph with <a href="https://example.com">link</a></p>'
    expect(classifyMailHtml(plainHtml)).toBe('plain')

    const darkDoc = buildMailSrcdoc(plainHtml, { theme: 'dark' })
    expect(darkDoc).toContain('background:#222729')
    expect(darkDoc).toContain('color:#FFFFFF')
    expect(darkDoc).toContain('a{color:#0A84FF}')

    const lightDoc = buildMailSrcdoc(plainHtml, { theme: 'light' })
    expect(lightDoc).toContain('background:#ffffff')
    expect(lightDoc).toContain('color:#202124')
    expect(lightDoc).toContain('a{color:#0066CC}')
  })

  it('classifies explicit light rich html as light and preserves white background in dark mode (AC-003)', () => {
    const lightHtml = '<div style="background-color: #ffffff; color: #333333;"><p>Newsletter</p></div>'
    expect(classifyMailHtml(lightHtml)).toBe('light')

    const darkDoc = buildMailSrcdoc(lightHtml, { theme: 'dark' })
    expect(darkDoc).toContain('background:#ffffff')
    expect(darkDoc).toContain('color:#202124')
  })

  it('classifies explicit dark html as dark (AC-003)', () => {
    const darkHtml = '<table bgcolor="#111111" style="color: #eeeeee"><tr><td>Dark promo</td></tr></table>'
    expect(classifyMailHtml(darkHtml)).toBe('dark')

    const darkDoc = buildMailSrcdoc(darkHtml, { theme: 'dark' })
    expect(darkDoc).toContain('background:#222729')
  })

  it('applies smart inversion filter to light html in dark mode and restores media colors (AC-001, AC-002)', () => {
    const lightHtml = '<div style="background-color: #ffffff; color: #333333;"><p>Newsletter</p><img src="test.png"></div>'
    const darkDoc = buildMailSrcdoc(lightHtml, { theme: 'dark' })
    expect(darkDoc).toContain('html{filter:invert(100%) hue-rotate(180deg);background:#ffffff}')
    expect(darkDoc).toContain('img,video,canvas{filter:invert(100%) hue-rotate(180deg) drop-shadow(0 0 1px rgba(0, 0, 0, 0.75))}')
  })

  it('does not apply inversion filter to plain or dark html in dark mode (AC-003)', () => {
    const plainHtml = '<p>Simple text</p>'
    const plainDoc = buildMailSrcdoc(plainHtml, { theme: 'dark' })
    expect(plainDoc).not.toContain('filter:invert')
    expect(plainDoc).toContain('background:#222729')

    const darkHtml = '<table bgcolor="#111111" style="color: #eeeeee"><tr><td>Dark promo</td></tr></table>'
    const darkDoc = buildMailSrcdoc(darkHtml, { theme: 'dark' })
    expect(darkDoc).not.toContain('filter:invert')
    expect(darkDoc).toContain('background:#222729')
  })

  it('respects darkModeInvert: false option to render un-inverted light html in dark mode (AC-004, AC-006)', () => {
    const lightHtml = '<div style="background-color: #ffffff"><p>Newsletter</p></div>'
    const doc = buildMailSrcdoc(lightHtml, { theme: 'dark', darkModeInvert: false })
    expect(doc).not.toContain('filter:invert')
    expect(doc).toContain('background:#ffffff')
  })

  it('never applies inversion filter in light mode regardless of classification (AC-005)', () => {
    const lightHtml = '<div style="background-color: #ffffff"><p>Newsletter</p></div>'
    const doc = buildMailSrcdoc(lightHtml, { theme: 'light' })
    expect(doc).not.toContain('filter:invert')
    expect(doc).toContain('background:#ffffff')
  })

  it('adapts iframe color-scheme meta and scrollbar styling to current theme', () => {
    const lightDoc = buildMailSrcdoc('<p>Hello</p>', { theme: 'light' })
    expect(lightDoc).toContain('<meta name="color-scheme" content="light">')
    expect(lightDoc).toContain(':root{color-scheme:light}')
    expect(lightDoc).toContain('scrollbar-color:rgba(0,0,0,0.28) transparent')

    const darkDoc = buildMailSrcdoc('<p>Hello</p>', { theme: 'dark' })
    expect(darkDoc).toContain('<meta name="color-scheme" content="dark">')
    expect(darkDoc).toContain(':root{color-scheme:dark}')
    expect(darkDoc).toContain('scrollbar-color:rgba(255,255,255,0.28) transparent')
  })

  it('reuses prepared sanitized html and classification when building srcdoc', () => {
    const sanitize = vi.spyOn(DOMPurify, 'sanitize')
    const prepared = prepareMailHtml('<div style="background:#fff"><script>bad()</script>safe</div>')
    const doc = buildMailSrcdoc('', {
      theme: 'dark',
      classification: prepared.classification,
      preparedHtml: prepared,
    })

    expect(sanitize).toHaveBeenCalledTimes(1)
    expect(doc).toContain('background:#ffffff')
    expect(doc).toContain('safe')
    expect(doc).not.toContain('bad()')
  })

  it('does not relax script/meta/style sanitization rules for dark theme adaptation', () => {
    const malicious = '<p>Hi</p><meta http-equiv="refresh" content="0"><style>body{color:red}</style><script>alert(1)</script>'
    const sanitized = sanitizeMailHtml(malicious)
    expect(sanitized).not.toMatch(/<script|<meta|<style/i)
    const doc = buildMailSrcdoc(malicious, { theme: 'dark' })
    expect(doc).not.toMatch(/alert\(1\)/)
    expect(doc).toContain("default-src 'none'")
  })
})

describe('t066: CID image rewriting and remote image detection', () => {
  it('normalizes CID according to RFC 2392 (separating URL percent-decode and header literal retention)', () => {
    // URL side: strictly decode percent-encoding once and lowercase
    expect(normalizeCidUrl('cid:foo%40bar.com')).toBe('foo@bar.com')
    expect(normalizeCidUrl('cid:<Foo%40Bar.com>')).toBe('foo@bar.com')
    expect(normalizeCidUrl('cid:<IMAGE_01.PNG>')).toBe('image_01.png')

    // Header side: strips angle brackets and lowercase, does not do unconstrained double percent-decode
    expect(normalizeHeaderContentId('<Foo%40Bar.com>')).toBe('foo%40bar.com')
    expect(normalizeHeaderContentId('simple-id@domain.com')).toBe('simple-id@domain.com')

    // Empty or malformed inputs
    expect(normalizeCidUrl('')).toBeNull()
    expect(normalizeCidUrl('cid:%')).toBeNull() // Malformed percent escape
    expect(normalizeCidUrl('cid:%E0%A4%A')).toBeNull() // Invalid UTF-8 sequence
    expect(normalizeHeaderContentId('')).toBeNull()

    // Length limit > 255 rejected
    expect(normalizeCidUrl('cid:' + 'a'.repeat(256))).toBeNull()
    expect(normalizeHeaderContentId('a'.repeat(256))).toBeNull()
  })

  it('rewrites matching CID images to signed preview URLs in offline DOM', () => {
    const html = '<p>Hello</p><img src="cid:logo.png" alt="Logo"><img src="cid:banner%40ex.com">'
    const attachments = [
      { content_id: 'logo.png', preview_url: '/api/mail/attachments/111/preview?token=tok1', is_inline: true },
      { content_id: '<banner@ex.com>', preview_url: '/api/mail/attachments/222/preview?token=tok2', is_inline: true },
    ]
    const rewritten = rewriteCidImages(html, attachments)
    expect(rewritten).toContain('src="/api/mail/attachments/111/preview?token=tok1"')
    expect(rewritten).toContain('src="/api/mail/attachments/222/preview?token=tok2"')
  })

  it('safely falls back to original when CID has no matching attachment, conflicts, or non-inline parts', () => {
    const html = '<img src="cid:unmatched@test">'
    const rewritten = rewriteCidImages(html, [])
    expect(rewritten).toBe(html)

    // Conflict case: two distinct attachments share the exact same normalized content_id
    const conflictAttachments = [
      { content_id: '<duplicate@test>', preview_url: '/api/mail/attachments/a1/preview', is_inline: true },
      { content_id: 'duplicate@test', preview_url: '/api/mail/attachments/a2/preview', is_inline: true },
    ]
    const conflictHtml = '<img src="cid:duplicate@test">'
    expect(rewriteCidImages(conflictHtml, conflictAttachments)).toBe(conflictHtml)

    // Non-inline attachment (is_inline === false) is excluded from inline image rewriting
    const regularAttachment = [
      { content_id: 'report.pdf', preview_url: '/api/mail/attachments/pdf/preview', is_inline: false },
    ]
    const regularHtml = '<img src="cid:report.pdf">'
    expect(rewriteCidImages(regularHtml, regularAttachment)).toBe(regularHtml)

    // Malformed percent escape safely falls back
    const malformedHtml = '<img src="cid:%">'
    expect(rewriteCidImages(malformedHtml, conflictAttachments)).toBe(malformedHtml)
  })

  it('detects external remote images accurately and ignores inline/preview/data URLs', () => {
    // External http / https / protocol-relative
    expect(hasRemoteImages('<img src="https://tracker.com/pixel.gif">')).toBe(true)
    expect(hasRemoteImages('<img src="http://example.com/logo.png">')).toBe(true)
    expect(hasRemoteImages('<img src="//cdn.example.com/banner.jpg">')).toBe(true)

    // Internal preview, data URI, or cid should NOT trigger remote image warning
    expect(hasRemoteImages('<img src="/api/mail/attachments/123/preview?token=xyz">')).toBe(false)
    expect(hasRemoteImages('<img src="data:image/png;base64,iVBORw0KGgo=">')).toBe(false)
    expect(hasRemoteImages('<img src="cid:inline_logo">')).toBe(false)
    expect(hasRemoteImages('<p>Plain text without images</p>')).toBe(false)
    expect(hasRemoteImages('')).toBe(false)
  })
})
