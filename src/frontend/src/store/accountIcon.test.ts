import { describe, expect, it } from 'vitest'
import { detectAccountBrand, getEmailDomain, getEmailInitial } from './accountIcon'

describe('accountIcon helpers (t010 AC-003, AC-004)', () => {
  it('extracts domain correctly', () => {
    expect(getEmailDomain('user@gmail.com')).toBe('gmail.com')
    expect(getEmailDomain('User@GMAIL.COM')).toBe('gmail.com')
    expect(getEmailDomain('invalid')).toBe('')
    expect(getEmailDomain('')).toBe('')
  })

  it('detects brand by exact domain match', () => {
    // Gmail
    expect(detectAccountBrand('a@gmail.com', 'imap')).toBe('gmail')
    expect(detectAccountBrand('a@googlemail.com', 'imap')).toBe('gmail')

    // Outlook / Hotmail / Live
    expect(detectAccountBrand('b@outlook.com', 'imap')).toBe('outlook')
    expect(detectAccountBrand('b@hotmail.com', 'imap')).toBe('outlook')
    expect(detectAccountBrand('b@live.com', 'imap')).toBe('outlook')
    expect(detectAccountBrand('b@msn.com', 'imap')).toBe('outlook')

    // NetEase (163 / 126 / yeah)
    expect(detectAccountBrand('c@163.com', 'imap')).toBe('163')
    expect(detectAccountBrand('c@126.com', 'imap')).toBe('163')
    expect(detectAccountBrand('c@yeah.net', 'imap')).toBe('163')
    expect(detectAccountBrand('c@netease.com', 'imap')).toBe('163')

    // QQ / Foxmail
    expect(detectAccountBrand('d@qq.com', 'imap')).toBe('qq')
    expect(detectAccountBrand('d@foxmail.com', 'imap')).toBe('qq')
  })

  it('rejects domain substring spoofing', () => {
    expect(detectAccountBrand('fake@notgmail.com', 'imap')).toBe('generic')
    expect(detectAccountBrand('fake@gmail.com.evil.org', 'imap')).toBe('generic')
    expect(detectAccountBrand('fake@myoutlook.com', 'imap')).toBe('generic')
    expect(detectAccountBrand('fake@163.com.cn', 'imap')).toBe('generic')
    expect(detectAccountBrand('fake@qq.com.fake.com', 'imap')).toBe('generic')
  })

  it('falls back to provider only when domain is unknown', () => {
    expect(detectAccountBrand('corp@company.com', 'gmail')).toBe('gmail')
    expect(detectAccountBrand('corp@company.com', 'graph')).toBe('outlook')
    expect(detectAccountBrand('corp@company.com', 'imap')).toBe('generic')
  })

  it('computes initials correctly including Unicode and surrogate pairs', () => {
    expect(getEmailInitial('john.doe@example.com')).toBe('J')
    expect(getEmailInitial('alice@example.com')).toBe('A')
    expect(getEmailInitial('李四@example.com')).toBe('李')
    expect(getEmailInitial('😀smile@example.com')).toBe('😀')
    expect(getEmailInitial('@example.com')).toBeNull()
    expect(getEmailInitial('   @example.com')).toBeNull()
    expect(getEmailInitial('')).toBeNull()
    expect(getEmailInitial(undefined)).toBeNull()
  })
})
