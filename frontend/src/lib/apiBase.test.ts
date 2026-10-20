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
})
