import { describe, expect, it } from 'vitest'
import { listTitle } from './listTitle'

describe('listTitle', () => {
  it('names the smart views', () => {
    expect(listTitle({ type: 'allInbox' }, 'all')).toBe('所有收件箱')
    expect(listTitle({ type: 'allInbox' }, 'unread')).toBe('未读邮件')
    expect(listTitle({ type: 'allInbox' }, 'flagged')).toBe('已标记')
  })
  it('names account folders', () => {
    expect(listTitle({ type: 'accountFolder', accountId: '1', email: 'a@x', folder: 'junkemail' }, 'all')).toBe('a@x · 垃圾邮件')
  })
})
