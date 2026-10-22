import { describe, expect, it } from 'vitest'
import { detectAccountBrand, getEmailDomain, getEmailInitial } from './accountIcon'

describe('accountIcon helpers (full 20 brand SVG suite)', () => {
  it('extracts domain correctly', () => {
    expect(getEmailDomain('user@gmail.com')).toBe('gmail.com')
    expect(getEmailDomain('User@GMAIL.COM')).toBe('gmail.com')
    expect(getEmailDomain('invalid')).toBe('')
    expect(getEmailDomain('')).toBe('')
  })

  // 架构升级：旧 t010 测试中 126/yeah/foxmail 被粗暴归入 163/qq，现已替换为 20 款独立专属矢量图标与精细化识别
  it('detects fine-grained brands by exact domain match', () => {
    // 谷歌系
    expect(detectAccountBrand('a@gmail.com', 'imap')).toBe('gmail')
    expect(detectAccountBrand('a@googlemail.com', 'imap')).toBe('gmail')
    expect(detectAccountBrand('a@google.com', 'imap')).toBe('google')

    // 微软系
    expect(detectAccountBrand('b@outlook.com', 'imap')).toBe('outlook')
    expect(detectAccountBrand('b@hotmail.com', 'imap')).toBe('outlook')
    expect(detectAccountBrand('b@live.com', 'imap')).toBe('outlook')
    expect(detectAccountBrand('b@msn.com', 'imap')).toBe('outlook')

    // 网易系独立图标
    expect(detectAccountBrand('c@163.com', 'imap')).toBe('163')
    expect(detectAccountBrand('c@vip.163.com', 'imap')).toBe('163')
    expect(detectAccountBrand('c@126.com', 'imap')).toBe('126')
    expect(detectAccountBrand('c@vip.126.com', 'imap')).toBe('126')
    expect(detectAccountBrand('c@yeah.net', 'imap')).toBe('yeah')
    expect(detectAccountBrand('c@netease.com', 'imap')).toBe('163')

    // 腾讯系与 Foxmail 独立图标
    expect(detectAccountBrand('d@qq.com', 'imap')).toBe('qq')
    expect(detectAccountBrand('d@vip.qq.com', 'imap')).toBe('qq')
    expect(detectAccountBrand('d@foxmail.com', 'imap')).toBe('foxmail')

    // 国际与隐私主流
    expect(detectAccountBrand('e@yandex.com', 'imap')).toBe('yandex')
    expect(detectAccountBrand('e@yandex.ru', 'imap')).toBe('yandex')
    expect(detectAccountBrand('f@yahoo.com', 'imap')).toBe('yahoo')
    expect(detectAccountBrand('g@icloud.com', 'imap')).toBe('icloud')
    expect(detectAccountBrand('g@me.com', 'imap')).toBe('icloud')
    expect(detectAccountBrand('h@proton.me', 'imap')).toBe('protonmail')

    // 国内运营商与门户
    expect(detectAccountBrand('i@139.com', 'imap')).toBe('139')
    expect(detectAccountBrand('j@189.cn', 'imap')).toBe('189')
    expect(detectAccountBrand('k@sina.com', 'imap')).toBe('sina')
    expect(detectAccountBrand('l@sohu.com', 'imap')).toBe('sohu')
    expect(detectAccountBrand('m@aliyun.com', 'imap')).toBe('aliyun')
  })

  // 架构升级：旧通用回退标记为 'generic'，现统一回退到标准 'default-mail' 图标
  it('rejects domain substring spoofing and falls back to default-mail', () => {
    expect(detectAccountBrand('fake@notgmail.com', 'imap')).toBe('default-mail')
    expect(detectAccountBrand('fake@gmail.com.evil.org', 'imap')).toBe('default-mail')
    expect(detectAccountBrand('fake@myoutlook.com', 'imap')).toBe('default-mail')
    expect(detectAccountBrand('fake@163.com.cn', 'imap')).toBe('default-mail')
    expect(detectAccountBrand('fake@qq.com.fake.com', 'imap')).toBe('default-mail')
  })

  it('falls back to provider or accountType when domain is unknown', () => {
    expect(detectAccountBrand('corp@company.com', 'gmail')).toBe('gmail')
    expect(detectAccountBrand('corp@company.com', 'graph')).toBe('outlook')
    expect(detectAccountBrand('corp@company.com', 'exchange')).toBe('exchange')
    expect(detectAccountBrand('corp@company.com', 'imap', 'enterprise')).toBe('enterprise')
    expect(detectAccountBrand('corp@company.com', 'imap')).toBe('default-mail')
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
