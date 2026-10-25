// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, Profiler } from 'react'
import { cleanup, render, waitFor } from '../test/render'
import UiReferenceOverlay from './UiReferenceOverlay'

describe('<UiReferenceOverlay /> (t011 AC-001 ~ AC-006)', () => {
  let writeTextMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('is inactive by default, toggles via shortcut and renders badges for visible data-ui elements (AC-001, AC-002)', async () => {
    // Add mock elements to DOM
    const el1 = document.createElement('button')
    el1.setAttribute('data-ui', 'ML03')
    vi.spyOn(el1, 'getBoundingClientRect').mockReturnValue({
      top: 50, left: 100, width: 80, height: 32, right: 180, bottom: 82, x: 100, y: 50, toJSON: () => {},
    })
    document.body.appendChild(el1)

    const el2 = document.createElement('div')
    el2.setAttribute('data-ui', 'ML02')
    vi.spyOn(el2, 'getBoundingClientRect').mockReturnValue({
      top: 10, left: 20, width: 120, height: 24, right: 140, bottom: 34, x: 20, y: 10, toJSON: () => {},
    })
    document.body.appendChild(el2)

    // Hidden element (width 0) should be excluded
    const hiddenEl = document.createElement('div')
    hiddenEl.setAttribute('data-ui', 'ML13')
    vi.spyOn(hiddenEl, 'getBoundingClientRect').mockReturnValue({
      top: 0, left: 0, width: 0, height: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => {},
    })
    document.body.appendChild(hiddenEl)

    const { container } = await render(<UiReferenceOverlay />)
    expect(container.querySelector('.ui-ref-badge')).toBeNull()

    // Trigger shortcut Ctrl + Shift + .
    window.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: '.',
        code: 'Period',
        ctrlKey: true,
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    )

    await waitFor(() => {
      const badges = [...document.querySelectorAll('.ui-ref-badge')].map((b) => b.textContent)
      expect(badges).toContain('ML03')
      expect(badges).toContain('ML02')
      expect(badges).not.toContain('ML13')
    })

    const underlyingClick = vi.fn()
    el1.addEventListener('click', underlyingClick)

    // Click on badge to copy reference (AC-005, t025 AC-001)
    const badgeML03 = [...document.querySelectorAll('.ui-ref-badge')].find((b) => b.textContent === 'ML03') as HTMLElement
    expect(badgeML03).toBeDefined()
    const { click: fireClick } = await import('../test/render')
    await fireClick(badgeML03)

    expect(writeTextMock).toHaveBeenCalledWith('[UI:ML03] 邮件列表 · 刷新并同步按钮')
    expect(underlyingClick).not.toHaveBeenCalled()

    await waitFor(() => {
      expect(document.body.textContent).toContain('已复制引用：[UI:ML03] 邮件列表 · 刷新并同步按钮')
    })

    // Press Escape to exit mode without triggering others (AC-006)
    const escEvent = new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    })
    const spiedStop = vi.spyOn(escEvent, 'stopPropagation')
    window.dispatchEvent(escEvent)

    expect(spiedStop).toHaveBeenCalled()
    await waitFor(() => {
      expect(document.querySelector('.ui-ref-badge')).toBeNull()
    })
  })

  it('displays clear failure feedback when clipboard copy fails or is rejected (AC-005)', async () => {
    writeTextMock.mockRejectedValue(new Error('Permission denied'))

    const el = document.createElement('div')
    el.setAttribute('data-ui', 'SB01')
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      top: 10, left: 10, width: 40, height: 40, right: 50, bottom: 50, x: 10, y: 10, toJSON: () => {},
    })
    document.body.appendChild(el)

    await render(<UiReferenceOverlay />)

    // Open mode
    window.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: '.',
        code: 'Period',
        metaKey: true,
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    )

    await waitFor(() => {
      expect(document.querySelector('.ui-ref-badge')).not.toBeNull()
    })

    const badge = document.querySelector('.ui-ref-badge') as HTMLElement
    const { click: fireClick } = await import('../test/render')
    await fireClick(badge)

    await waitFor(() => {
      expect(document.body.textContent).toContain('复制失败')
    })
  })

  it('coalesces external mutations and skips overlay or unchanged badge scans', async () => {
    const element = document.createElement('button')
    element.setAttribute('data-ui', 'ML03')
    const rect = vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
      top: 50, left: 100, width: 80, height: 32, right: 180, bottom: 82, x: 100, y: 50, toJSON: () => {},
    })
    document.body.appendChild(element)

    const frames: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      frames.push(callback)
      return frames.length
    })
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
    let commits = 0
    await render(
      <Profiler id="ui-reference" onRender={() => { commits += 1 }}>
        <UiReferenceOverlay />
      </Profiler>,
    )

    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', {
        key: '.', code: 'Period', ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true,
      }))
    })
    await waitFor(() => expect(document.querySelector('.ui-ref-badge')).not.toBeNull())
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })

    // Rendering the overlay's own badge must not schedule another full scan.
    expect(frames).toHaveLength(0)
    const stableCommitCount = commits

    document.body.appendChild(document.createElement('div'))
    await waitFor(() => expect(frames).toHaveLength(1))
    document.body.appendChild(document.createElement('div'))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    expect(frames).toHaveLength(1)

    await act(async () => { frames.shift()?.(0) })
    expect(rect).toHaveBeenCalledTimes(2)
    expect(commits).toBe(stableCommitCount)
  })

  it('displays failure feedback when navigator.clipboard is missing (t025 AC-004)', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
    })

    const el = document.createElement('div')
    el.setAttribute('data-ui', 'SB01')
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      top: 10, left: 10, width: 40, height: 40, right: 50, bottom: 50, x: 10, y: 10, toJSON: () => {},
    })
    document.body.appendChild(el)

    await render(<UiReferenceOverlay />)

    window.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: '.',
        code: 'Period',
        metaKey: true,
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    )

    await waitFor(() => {
      expect(document.querySelector('.ui-ref-badge')).not.toBeNull()
    })

    const badge = document.querySelector('.ui-ref-badge') as HTMLElement
    const { click: fireClick } = await import('../test/render')
    await fireClick(badge)

    await waitFor(() => {
      expect(document.body.textContent).toContain('复制失败')
    })
  })

  it('copies via document.execCommand when navigator.clipboard is missing and fallback succeeds', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
    })
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    const el = document.createElement('div')
    el.setAttribute('data-ui', 'SB02')
    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      top: 10, left: 10, width: 40, height: 40, right: 50, bottom: 50, x: 10, y: 10, toJSON: () => {},
    })
    document.body.appendChild(el)

    await render(<UiReferenceOverlay />)

    window.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: '.',
        code: 'Period',
        metaKey: true,
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    )

    await waitFor(() => {
      expect(document.querySelector('.ui-ref-badge')).not.toBeNull()
    })

    const badge = document.querySelector('.ui-ref-badge') as HTMLElement
    const { click: fireClick } = await import('../test/render')
    await fireClick(badge)

    await waitFor(() => {
      expect(execCommand).toHaveBeenCalledWith('copy')
      expect(document.body.textContent).toContain('已复制引用')
    })
  })
})
