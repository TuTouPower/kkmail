import { describe, expect, it } from 'vitest'
import { parseSendRecipients, replyAllRecipients, replyRecipient } from './recipients'

describe('recipients', () => {
  it('extracts the sender address from a display name', () => {
    expect(replyRecipient('Alice <alice@example.com>')).toBe('alice@example.com')
    expect(replyRecipient('未知')).toBe('')
  })
  it('parses send recipients into a de-duplicated list', () => {
    expect(parseSendRecipients('A@Example.com; b@example.com\nA@example.com')).toEqual({
      recipients: ['a@example.com', 'b@example.com'],
      error: '',
    })
    expect(parseSendRecipients('not-an-email').error).toBe('请填写有效的收件人邮箱地址')
    expect(parseSendRecipients('').error).toBe('请至少填写一个收件人')
  })
  it('reply-all drops self and duplicates', () => {
    expect(replyAllRecipients('Alice <alice@example.com>', ['me@outlook.com, Bob <bob@example.com>', 'ALICE@example.com'], 'Me@Outlook.com'))
      .toBe('alice@example.com, bob@example.com')
  })
})
