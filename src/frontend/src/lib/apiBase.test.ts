// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiBaseUrl } from './apiBase'

describe('apiBaseUrl', () => {
  afterEach(() => {
    delete window.__KKMAIL_CONFIG__
    vi.unstubAllEnvs()
  })

  it('defaults to same-origin (empty string)', () => {
    expect(apiBaseUrl()).toBe('')
  })

  it('uses VITE_API_BASE and strips trailing slashes', () => {
    vi.stubEnv('VITE_API_BASE', 'http://127.0.0.1:8000//')
    expect(apiBaseUrl()).toBe('http://127.0.0.1:8000')
  })

  it('runtime config overrides the build-time value', () => {
    vi.stubEnv('VITE_API_BASE', 'http://build.example')
    window.__KKMAIL_CONFIG__ = { apiBase: 'http://runtime.example/' }
    expect(apiBaseUrl()).toBe('http://runtime.example')
  })

  it('accepts https bases with a path and strips trailing slashes (A377)', () => {
    window.__KKMAIL_CONFIG__ = { apiBase: 'https://api.example.com/v1///' }
    expect(apiBaseUrl()).toBe('https://api.example.com/v1')
  })

  it('rejects non-http(s) and scheme-relative bases (A377)', () => {
    for (const bad of ['javascript:alert(1)', 'data:text/html;base64,x', 'ftp://files.example', '//evil.example', 'evil.example', '/relative']) {
      window.__KKMAIL_CONFIG__ = { apiBase: bad }
      expect(apiBaseUrl()).toBe('')
    }
  })

  it('rejects bases with embedded credentials (A377)', () => {
    window.__KKMAIL_CONFIG__ = { apiBase: 'http://user:pass@api.example.com' }
    expect(apiBaseUrl()).toBe('')
  })

  it('fails closed to same-origin when the runtime override is invalid, ignoring the build-time value (A377)', () => {
    vi.stubEnv('VITE_API_BASE', 'http://build.example')
    window.__KKMAIL_CONFIG__ = { apiBase: 'javascript:alert(1)' }
    expect(apiBaseUrl()).toBe('')
  })

  it('rejects an invalid build-time base too (A377)', () => {
    vi.stubEnv('VITE_API_BASE', 'data:text/html;base64,x')
    expect(apiBaseUrl()).toBe('')
  })
})
