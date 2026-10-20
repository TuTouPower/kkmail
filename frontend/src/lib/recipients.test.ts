import { describe, expect, it } from 'vitest'
import { replyAllRecipients, replyRecipient } from './recipients'

describe('recipients', () => {
  it('extracts the sender address from a display name', () => {
    expect(replyRecipient('Alice <alice@example.com>')).toBe('alice@example.com')
    expect(replyRecipient('未知')).toBe('')
  })
  it('reply-all drops self and duplicates', () => {
    expect(replyAllRecipients('Alice <alice@example.com>', ['me@outlook.com, Bob <bob@example.com>', 'ALICE@example.com'], 'Me@Outlook.com'))
      .toBe('alice@example.com, bob@example.com')
  })
})
