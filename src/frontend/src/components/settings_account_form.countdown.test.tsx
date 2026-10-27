import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { DeviceCodeCountdown } from './settings_account_form'
import { cleanup, render } from '../test/render'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('A124: countdown ticks on its own without any parent state', async () => {
  const expiresAt = Math.floor(Date.now() / 1000) + 90
  const { container } = await render(<DeviceCodeCountdown expiresAt={expiresAt} />)
  const before = Number(container.textContent)
  expect(before).toBe(90)
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)) })
  const after = Number(container.textContent)
  expect(after).toBeLessThan(before)
  expect(after).toBeGreaterThanOrEqual(88)
})

it('A124: countdown clears its interval on unmount', async () => {
  const clearSpy = vi.spyOn(window, 'clearInterval')
  const expiresAt = Math.floor(Date.now() / 1000) + 90
  const { unmount } = await render(<DeviceCodeCountdown expiresAt={expiresAt} />)
  unmount()
  expect(clearSpy).toHaveBeenCalled()
})

it('A124: countdown never renders a negative remainder', async () => {
  const expiresAt = Math.floor(Date.now() / 1000) - 5
  const { container } = await render(<DeviceCodeCountdown expiresAt={expiresAt} />)
  expect(container.textContent).toBe('0')
})
