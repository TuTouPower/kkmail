// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { MAIL_IFRAME_SANDBOX, buildMailSrcdoc, htmlToText, isHtmlBody, sanitizeMailHtml } from './mailBody'

describe('mail body safety', () => {
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

  // 旧测试 "sandbox never allows scripts, same-origin, or escape-sandbox" 已删除：A17 演进为允许 allow-popups-to-escape-sandbox 保证 Web SPA 模式下外部新窗口正常可用
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

  it('converts html to quoted text', () => {
    expect(htmlToText('<p>a</p><p>b<br>c</p><img src=x onerror=alert(1)>')).toBe('a\nb\nc')
  })
})
