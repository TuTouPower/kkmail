// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { render } from '../test/render'
import AccountIcon from './AccountIcon'
import { useMailStore } from '../store/mailStore'

describe('<AccountIcon /> (full 20 brand SVG suite)', () => {
  it('renders null in none mode without any DOM node (AC-002)', async () => {
    useMailStore.setState({ accountIconMode: 'none' })
    const { container } = await render(<AccountIcon email="user@gmail.com" provider="imap" />)
    expect(container.querySelector('.account-dot')).toBeNull()
    expect(container.innerHTML).toBe('')
  })

  // 架构升级：旧 t010 测试断言字符伪图标（G/O/163/QQ），现升级为渲染全量矢量 SVG 真实图标，未匹配回退到 default-mail.svg
  it('renders brand mode with exact SVG brand icons and default-mail fallback', async () => {
    useMailStore.setState({ accountIconMode: 'brand' })

    // Gmail (SVG)
    const { container: c1 } = await render(<AccountIcon email="test@gmail.com" provider="imap" />)
    const dot1 = c1.querySelector('.account-dot')
    expect(dot1?.className).toContain('account-brand-gmail')
    expect(dot1?.querySelector('svg')).not.toBeNull()
    expect(dot1?.getAttribute('title')).toBe('Gmail')

    // Outlook (SVG)
    const { container: c2 } = await render(<AccountIcon email="test@outlook.com" provider="imap" />)
    const dot2 = c2.querySelector('.account-dot')
    expect(dot2?.className).toContain('account-brand-outlook')
    expect(dot2?.querySelector('svg')).not.toBeNull()
    expect(dot2?.getAttribute('title')).toBe('Outlook')

    // 163 (SVG)
    const { container: c3 } = await render(<AccountIcon email="test@163.com" provider="imap" />)
    const dot3 = c3.querySelector('.account-dot')
    expect(dot3?.className).toContain('account-brand-163')
    expect(dot3?.querySelector('svg')).not.toBeNull()
    expect(dot3?.getAttribute('title')).toBe('163邮箱')

    // QQ (SVG 修正2方案A企鹅)
    const { container: c4 } = await render(<AccountIcon email="test@qq.com" provider="imap" />)
    const dot4 = c4.querySelector('.account-dot')
    expect(dot4?.className).toContain('account-brand-qq')
    expect(dot4?.querySelector('svg')).not.toBeNull()
    expect(dot4?.getAttribute('title')).toBe('QQ邮箱')

    // Yandex (SVG 修正1方案A大写Y)
    const { container: c5 } = await render(<AccountIcon email="test@yandex.com" provider="imap" />)
    const dot5 = c5.querySelector('.account-dot')
    expect(dot5?.className).toContain('account-brand-yandex')
    expect(dot5?.querySelector('svg')).not.toBeNull()
    expect(dot5?.getAttribute('title')).toBe('Yandex')

    // 126 (细分独立图标)
    const { container: c6 } = await render(<AccountIcon email="test@126.com" provider="imap" />)
    const dot6 = c6.querySelector('.account-dot')
    expect(dot6?.className).toContain('account-brand-126')
    expect(dot6?.querySelector('svg')).not.toBeNull()

    // 未知域名 -> 回退到默认邮箱 default-mail SVG 图标
    const { container: c7 } = await render(<AccountIcon email="test@custom.org" provider="imap" />)
    const dot7 = c7.querySelector('.account-dot')
    expect(dot7?.className).toContain('account-brand-default-mail')
    expect(dot7?.querySelector('svg')).not.toBeNull()
    expect(dot7?.getAttribute('title')).toBe('默认邮箱')
  })

  it('sanitizes server-supplied groupColor before using it as background (A371)', async () => {
    useMailStore.setState({ accountIconMode: 'initials' })

    const { container: evil } = await render(
      <AccountIcon email="alice@custom.org" provider="imap" groupColor="url(https://attacker.example/track.png)" />,
    )
    const evilBg = (evil.querySelector('.account-dot') as HTMLElement).style.background
    expect(evilBg).not.toContain('url')
    expect(evilBg).not.toContain('attacker')

    const { container: evil2 } = await render(
      <AccountIcon email="@custom.org" provider="imap" groupColor="red; background-image:url(https://attacker.example/x)" />,
    )
    const evil2Bg = (evil2.querySelector('.account-dot') as HTMLElement).style.background
    expect(evil2Bg).not.toContain('url')
    expect(evil2Bg).not.toContain('attacker')

    const { container: ok } = await render(
      <AccountIcon email="alice@custom.org" provider="imap" groupColor="#0a8f3c" />,
    )
    const okBg = (ok.querySelector('.account-dot') as HTMLElement).style.background
    expect(okBg).toContain('rgb(10, 143, 60)')
  })

  it('renders initials mode with username first character (AC-004)', async () => {
    useMailStore.setState({ accountIconMode: 'initials' })

    const { container: c1 } = await render(<AccountIcon email="alice@custom.org" provider="imap" />)
    const dot1 = c1.querySelector('.account-dot')
    expect(dot1?.textContent).toBe('A')

    const { container: c2 } = await render(<AccountIcon email="张三@custom.org" provider="imap" />)
    const dot2 = c2.querySelector('.account-dot')
    expect(dot2?.textContent).toBe('张')

    // Empty username -> generic icon
    const { container: c3 } = await render(<AccountIcon email="@custom.org" provider="imap" />)
    const dot3 = c3.querySelector('.account-dot')
    expect(dot3?.className).toContain('account-generic')
    expect(dot3?.querySelector('svg')).not.toBeNull()
  })
})
