import { describe, expect, it } from 'vitest'
import { isMailCoreEnabled, mailCoreBaseUrl } from './mailCoreFlag'

describe('mailCoreFlag', () => {
  it('exports helpers', () => {
    // Default vitest env has no VITE_MAIL_CORE → disabled
    expect(typeof isMailCoreEnabled()).toBe('boolean')
    expect(mailCoreBaseUrl()).toMatch(/mail-core|http/)
  })
})
