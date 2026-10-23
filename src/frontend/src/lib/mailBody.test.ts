// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import {
  MAIL_IFRAME_SANDBOX,
  buildMailSrcdoc,
  classifyMailHtml,
  isHtmlBody,
  sanitizeMailHtml,
} from './mailBody'

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

  it('enforces rel="noopener noreferrer" and target="_blank" on anchor tags', () => {
    const out = sanitizeMailHtml('<a href="https://example.com">link</a>')
    expect(out).toContain('target="_blank"')
    expect(out).toContain('rel="noopener noreferrer"')
  })

  it('blocks remote images by default and allows them only on explicit opt-in', () => {
    expect(buildMailSrcdoc('<img src="https://evil/x.png">')).not.toContain('img-src https:')
    expect(buildMailSrcdoc('<img src="https://x/y.png">', { loadRemoteImages: true })).toContain('img-src https: http: data: cid:')
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

  it('does not relax script/meta/style sanitization rules for dark theme adaptation', () => {
    const malicious = '<p>Hi</p><meta http-equiv="refresh" content="0"><style>body{color:red}</style><script>alert(1)</script>'
    const sanitized = sanitizeMailHtml(malicious)
    expect(sanitized).not.toMatch(/<script|<meta|<style/i)
    const doc = buildMailSrcdoc(malicious, { theme: 'dark' })
    expect(doc).not.toMatch(/alert\(1\)/)
    expect(doc).toContain("default-src 'none'")
  })
})
