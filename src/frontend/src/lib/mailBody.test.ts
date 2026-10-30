// @vitest-environment jsdom
import DOMPurify from 'dompurify'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  MAIL_IFRAME_SANDBOX,
  buildMailSrcdoc,
  classifyMailHtml,
  isHtmlBody,
  prepareMailHtml,
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

  it('wraps output in a CSP document with rel="noopener noreferrer" base and no-referrer meta', () => {
    const doc = buildMailSrcdoc('<img src=x onerror=alert(1)>')
    expect(doc).toContain("default-src 'none'")
    expect(doc).toContain('img-src data: cid:')
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

  it('blocks remote images by default and allows them only on explicit opt-in', () => {
    expect(buildMailSrcdoc('<img src="https://evil/x.png">')).not.toContain('img-src https:')
    expect(buildMailSrcdoc('<img src="https://x/y.png">', { loadRemoteImages: true })).toContain('img-src https: http: data: cid:')
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
    expect(darkDoc).toContain('img,video,canvas,picture{filter:invert(100%) hue-rotate(180deg) drop-shadow(0 0 1px rgba(255, 255, 255, 0.7))}')
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
