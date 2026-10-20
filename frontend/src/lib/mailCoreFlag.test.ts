// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { isMailCoreEnabled, mailCoreBaseUrl } from './mailCoreFlag'

describe('mailCoreFlag', () => {
  afterEach(() => {
    if (typeof window !== 'undefined') delete window.__KKMAIL_CONFIG__
  })

  it('exports helpers', () => {
    expect(typeof isMailCoreEnabled()).toBe('boolean')
    expect(mailCoreBaseUrl()).toMatch(/mail-core|http/)
  })

  it('runtime MAIL_CORE_DEFAULT enables without rebuild', () => {
    window.__KKMAIL_CONFIG__ = { mailCoreDefault: true, mailCoreBase: 'http://127.0.0.1:8000' }
    // Only asserts runtime path when Vite env did not force off (vitest default unset)
    if (!String(import.meta.env.VITE_MAIL_CORE || '')) {
      expect(isMailCoreEnabled()).toBe(true)
      expect(mailCoreBaseUrl()).toBe('http://127.0.0.1:8000')
    }
  })
})
