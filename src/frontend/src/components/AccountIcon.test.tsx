// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { render } from '../test/render'
import AccountIcon from './AccountIcon'
import { useMailStore } from '../store/mailStore'

describe('<AccountIcon /> (t010 AC-001 ~ AC-005)', () => {
  it('renders null in none mode without any DOM node (AC-002)', async () => {
    useMailStore.setState({ accountIconMode: 'none' })
    const { container } = await render(<AccountIcon email="user@gmail.com" provider="imap" />)
    expect(container.querySelector('.account-dot')).toBeNull()
    expect(container.innerHTML).toBe('')
  })

  it('renders brand mode with exact brand indicators (AC-003)', async () => {
    useMailStore.setState({ accountIconMode: 'brand' })

    // Gmail
    const { container: c1 } = await render(<AccountIcon email="test@gmail.com" provider="imap" />)
    const dot1 = c1.querySelector('.account-dot')
    expect(dot1?.textContent).toBe('G')
    expect(dot1?.className).toContain('account-brand-gmail')

    // Outlook
    const { container: c2 } = await render(<AccountIcon email="test@outlook.com" provider="imap" />)
    const dot2 = c2.querySelector('.account-dot')
    expect(dot2?.textContent).toBe('O')
    expect(dot2?.className).toContain('account-brand-outlook')

    // 163
    const { container: c3 } = await render(<AccountIcon email="test@163.com" provider="imap" />)
    const dot3 = c3.querySelector('.account-dot')
    expect(dot3?.textContent).toBe('163')
    expect(dot3?.className).toContain('account-brand-163')

    // QQ
    const { container: c4 } = await render(<AccountIcon email="test@qq.com" provider="imap" />)
    const dot4 = c4.querySelector('.account-dot')
    expect(dot4?.textContent).toBe('QQ')
    expect(dot4?.className).toContain('account-brand-qq')

    // Unknown domain -> generic mail icon
    const { container: c5 } = await render(<AccountIcon email="test@custom.org" provider="imap" />)
    const dot5 = c5.querySelector('.account-dot')
    expect(dot5?.className).toContain('account-brand-generic')
    expect(dot5?.querySelector('svg')).not.toBeNull()
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
