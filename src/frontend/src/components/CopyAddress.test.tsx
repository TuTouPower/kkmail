// @vitest-environment jsdom
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CopyAddress from './CopyAddress'
import { cleanup, render, waitFor } from '../test/render'

function setClipboard(writeText?: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  })
}

afterEach(() => {
  cleanup()
  Reflect.deleteProperty(navigator, 'clipboard')
  vi.useRealTimers()
})

describe('<CopyAddress />', () => {
  it('copies the plain address, reports success for two seconds, and restarts the timeout', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)
    const { container } = await render(<CopyAddress address="jane@example.test">jane@example.test</CopyAddress>)
    const button = container.querySelector<HTMLButtonElement>('button[aria-label="复制邮箱地址 jane@example.test"]')!
    expect(button.title).toBe('复制邮箱地址')

    await act(async () => { button.click(); await Promise.resolve() })
    expect(writeText).toHaveBeenCalledWith('jane@example.test')
    expect(document.body.querySelector('[role="status"]')?.textContent).toBe('已复制地址')
    await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
    await act(async () => { button.click(); await Promise.resolve() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
    expect(document.body.querySelector('[role="status"]')?.textContent).toBe('已复制地址')
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    expect(document.body.querySelector('[role="status"]')).toBeNull()
  })

  it('shows the clipboard rejection reason and reports an unavailable Clipboard API', async () => {
    setClipboard(() => Promise.reject(new Error('permission denied')))
    const rejected = await render(<CopyAddress address="jane@example.test">jane@example.test</CopyAddress>)
    await act(async () => { rejected.container.querySelector('button')!.click() })
    await waitFor(() => expect(document.body.querySelector('[role="status"]')?.textContent).toContain('permission denied'))
    expect(document.body.querySelector('[role="status"]')?.textContent).toContain('手动选择并复制地址')
    cleanup()

    setClipboard()
    const unavailable = await render(<CopyAddress address="jane@example.test">jane@example.test</CopyAddress>)
    await act(async () => { unavailable.container.querySelector('button')!.click() })
    await waitFor(() => expect(document.body.querySelector('[role="status"]')?.textContent).toContain('剪贴板'))
    expect(document.body.querySelector('[role="status"]')?.textContent).toContain('手动选择并复制地址')
  })

  it('copies via document.execCommand fallback in insecure context without navigator.clipboard', async () => {
    setClipboard()
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand
    const { container } = await render(<CopyAddress address="fallback@example.test">fallback@example.test</CopyAddress>)
    const button = container.querySelector<HTMLButtonElement>('button')!
    await act(async () => { button.click(); await Promise.resolve() })
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.body.querySelector('[role="status"]')?.textContent).toBe('已复制地址')
  })

  it('clears its feedback timer when unmounted', async () => {
    vi.useFakeTimers()
    setClipboard(vi.fn().mockResolvedValue(undefined))
    const { container, unmount } = await render(<CopyAddress address="jane@example.test">jane@example.test</CopyAddress>)
    await act(async () => { container.querySelector('button')!.click(); await Promise.resolve() })
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('ignores a clipboard write that settles after unmount', async () => {
    vi.useFakeTimers()
    let resolveWrite!: () => void
    setClipboard(() => new Promise<void>((resolve) => { resolveWrite = resolve }))
    const { container, unmount } = await render(<CopyAddress address="jane@example.test">jane@example.test</CopyAddress>)
    await act(async () => { container.querySelector('button')!.click(); await Promise.resolve() })
    unmount()
    await act(async () => { resolveWrite(); await Promise.resolve() })

    expect(document.body.querySelector('[role="status"]')).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })
})
