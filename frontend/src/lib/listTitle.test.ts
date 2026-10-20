import { describe, expect, it } from 'vitest'
import { listTitle } from './listTitle'

describe('listTitle', () => {
  it('names the smart views', () => {
    expect(listTitle({ type: 'allInbox' }, 'all')).toBe('所有收件箱')
    expect(listTitle({ type: 'allInbox' }, 'unread')).toBe('未读邮件')
    expect(listTitle({ type: 'allInbox' }, 'flagged')).toBe('已标记')
  })
  it('names the account inbox', () => {
    expect(listTitle({ type: 'account', accountId: '1', email: 'a@x' }, 'all')).toBe('a@x · 收件箱')
  })
})
