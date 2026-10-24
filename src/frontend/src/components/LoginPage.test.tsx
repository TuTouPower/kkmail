// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage'
import { api } from '../api/client'
import { cleanup, click, render, typeInto, waitFor } from '../test/render'

describe('<LoginPage />', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
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

  it('submits the entered password and calls onSuccess after api.login resolves', async () => {
    const login = vi.spyOn(api, 'login').mockResolvedValue()
    const onSuccess = vi.fn()
    const { container } = await render(<LoginPage onSuccess={onSuccess} />)
    const password = container.querySelector<HTMLInputElement>('#login-password')
    const submit = container.querySelector<HTMLButtonElement>('button[type="submit"]')

    await typeInto(password, 'correct horse battery staple')
    await click(submit)
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))

    expect(login).toHaveBeenCalledWith('correct horse battery staple')
  })

  it('shows the server message when api.login rejects', async () => {
    vi.spyOn(api, 'login').mockRejectedValue({ status: 401, message: '密码错误' })
    const { container } = await render(<LoginPage onSuccess={() => {}} />)
    const password = container.querySelector<HTMLInputElement>('#login-password')
    const submit = container.querySelector<HTMLButtonElement>('button[type="submit"]')

    await typeInto(password, 'wrong password')
    await click(submit)
    await waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toBe('密码错误'))
  })

  it('disables submit while loading and ignores a second click', async () => {
    let resolveLogin!: () => void
    const login = vi.spyOn(api, 'login').mockImplementation(
      () => new Promise<void>((resolve) => { resolveLogin = resolve }),
    )
    const onSuccess = vi.fn()
    const { container } = await render(<LoginPage onSuccess={onSuccess} />)
    const password = container.querySelector<HTMLInputElement>('#login-password')
    const submit = container.querySelector<HTMLButtonElement>('button[type="submit"]')

    await typeInto(password, 'correct horse battery staple')
    await click(submit)
    expect(submit?.disabled).toBe(true)
    await click(submit)

    expect(login).toHaveBeenCalledTimes(1)
    resolveLogin()
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })
})
