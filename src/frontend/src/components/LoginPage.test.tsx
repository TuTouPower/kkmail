// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage'
import { cleanup, render } from '../test/render'

describe('<LoginPage />', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders web password hint using MAIL_CORE_LOGIN_PASSWORD without LOGIN_PASSWORD', async () => {
    // Standard web environment
    delete (window as unknown as { kkmailDesktop?: unknown }).kkmailDesktop

    const { container } = await render(<LoginPage onSuccess={() => {}} />)
    const text = container.textContent || ''
    expect(text).toContain('MAIL_CORE_LOGIN_PASSWORD')
    expect(text).toContain('MAIL_CORE_LOGIN_PASSWORD_HASH')
    expect(text).not.toContain('/ LOGIN_PASSWORD')
  })

  it('renders desktop password hint when kkmailDesktop is available', async () => {
    // Desktop environment
    ;(window as unknown as { kkmailDesktop?: unknown }).kkmailDesktop = { platform: 'darwin' }

    const { container } = await render(<LoginPage onSuccess={() => {}} />)
    const text = container.textContent || ''
    expect(text).toContain('初始密码对话框')
  })
})
