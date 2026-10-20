// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { isMailCoreEnabled, mailCoreBaseUrl } from './mailCoreFlag'

describe('mailCoreFlag', () => {
  afterEach(() => {
    if (typeof window !== 'undefined') delete window.__KKMAIL_CONFIG__
  })

  it('mail-core enabled by default', () => {
    expect(isMailCoreEnabled()).toBe(true)
  })

  it('runtime base overrides same-origin default', () => {
    window.__KKMAIL_CONFIG__ = { mailCoreBase: 'http://127.0.0.1:8000' }
    expect(mailCoreBaseUrl()).toBe('http://127.0.0.1:8000')
  })

  it('same-origin default is empty string', () => {
    expect(mailCoreBaseUrl()).toBe('')
  })
})
