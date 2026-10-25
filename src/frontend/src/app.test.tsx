// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import { api } from './api/client'
import { cleanup, click, render, waitFor } from './test/render'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('shows a retry state when the initial session check fails', async () => {
  const checkSession = vi.spyOn(api, 'checkSession')
    .mockRejectedValueOnce(new Error('mail-core unavailable'))
    .mockResolvedValueOnce(false)
  const { container } = await render(<App />)

  await waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain('无法连接 mail-core'))
  expect(container.querySelector('#login-password')).toBeNull()

  await click(container.querySelector('[data-testid="retry-session-check"]'))

  await waitFor(() => expect(container.querySelector('#login-password')).not.toBeNull())
  expect(checkSession).toHaveBeenCalledTimes(2)
})
