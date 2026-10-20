import { describe, expect, it } from 'vitest'
import { mailKey } from './mailKey'

describe('mailKey', () => {
  it('differs for the same UID in different folders', () => {
    const inbox = mailKey({ accountEmail: 'a@x.test', folder: 'inbox', id: '101' })
    const junk = mailKey({ accountEmail: 'a@x.test', folder: 'junkemail', id: '101' })
    expect(inbox).not.toBe(junk)
  })
  it('differs across accounts and is case-insensitive on account', () => {
    expect(mailKey({ accountEmail: 'A@x.test', id: '1' })).toBe(mailKey({ accountEmail: 'a@x.test', folder: 'inbox', id: '1' }))
    expect(mailKey({ accountEmail: 'a@x.test', id: '1' })).not.toBe(mailKey({ accountEmail: 'b@x.test', id: '1' }))
  })
})
