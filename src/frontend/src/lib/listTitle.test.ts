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
  it('reflects the flagged filter in group titles', () => {
    expect(listTitle({ type: 'group', groupId: 'g1', groupName: '工作组', category: 'inbox' }, 'flagged')).toBe('工作组 · 已标记')
    expect(listTitle({ type: 'group', groupId: 'g1', groupName: '工作组', category: 'inbox' }, 'unread')).toBe('工作组 · 未读邮件')
    expect(listTitle({ type: 'group', groupId: 'g1', groupName: '工作组', category: 'sent' }, 'flagged')).toBe('工作组 · 已发邮件 · 已标记')
    expect(listTitle({ type: 'group', groupId: 'g1', groupName: '工作组', category: 'unread' }, 'flagged')).toBe('工作组 · 所有未读 · 已标记')
  })
  it('reflects the filter in favorite non-inbox titles', () => {
    expect(listTitle({ type: 'favorite', category: 'drafts' }, 'flagged')).toBe('草稿箱 · 已标记')
    expect(listTitle({ type: 'favorite', category: 'drafts', accountId: '1', email: 'a@x' }, 'flagged')).toBe('a@x · 草稿箱 · 已标记')
    expect(listTitle({ type: 'favorite', category: 'sent' }, 'unread')).toBe('已发邮件 · 未读')
    expect(listTitle({ type: 'favorite', category: 'unread' }, 'flagged')).toBe('所有未读 · 已标记')
  })
  it('names the favorite views and specific folders (t008 AC-001, AC-004)', () => {
    expect(listTitle({ type: 'favorite', category: 'drafts' }, 'all')).toBe('草稿箱')
    expect(listTitle({ type: 'favorite', category: 'trash' }, 'all')).toBe('废纸篓')
    expect(listTitle({ type: 'favorite', category: 'junk' }, 'all')).toBe('垃圾邮件')
    expect(listTitle({ type: 'favorite', category: 'sent' }, 'all')).toBe('已发邮件')
    expect(listTitle({ type: 'favorite', category: 'drafts', accountId: '1', email: 'a@x' }, 'all')).toBe('a@x · 草稿箱')
    expect(listTitle({ type: 'folder', accountId: '1', email: 'a@x', folderId: 'f1', folderName: 'MyFolder' }, 'all')).toBe('a@x · MyFolder')
  })
})
