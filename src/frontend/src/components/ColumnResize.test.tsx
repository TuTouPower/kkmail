// @vitest-environment jsdom
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ColumnResize from './ColumnResize'
import { cleanup, render } from '../test/render'

afterEach(() => cleanup())

function key(el: Element, k: string) {
  act(() => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }))
  })
}

function keyEvent(el: Element, type: 'keydown' | 'keyup', k: string, repeat = false) {
  act(() => {
    el.dispatchEvent(new KeyboardEvent(type, { key: k, bubbles: true, repeat }))
  })
}

describe('ColumnResize', () => {
  it('renders an accessible, focusable vertical separator', async () => {
    const { container } = await render(<ColumnResize ariaLabel="调整列宽" value={300} min={180} max={420} onDrag={() => {}} />)
    const handle = container.querySelector('[role="separator"]')
    expect(handle).not.toBeNull()
    expect(handle?.getAttribute('aria-orientation')).toBe('vertical')
    expect(handle?.getAttribute('aria-label')).toBe('调整列宽')
    expect(handle?.getAttribute('tabindex')).toBe('0')
    expect(handle?.getAttribute('aria-valuemin')).toBe('180')
    expect(handle?.getAttribute('aria-valuemax')).toBe('420')
    expect(handle?.getAttribute('aria-valuenow')).toBe('300')
  })

  it('arrow keys resize by 8px steps and other keys are ignored', async () => {
    const onDrag = vi.fn()
    const { container } = await render(<ColumnResize ariaLabel="resize" value={300} min={180} max={420} onDrag={onDrag} />)
    const handle = container.querySelector('[role="separator"]')!
    key(handle, 'ArrowLeft')
    key(handle, 'ArrowRight')
    key(handle, 'ArrowRight')
    key(handle, 'Enter')
    expect(onDrag.mock.calls).toEqual([[-8], [8], [8]])
  })

  it('keyboard long-press resizes on repeats but fires onDragEnd only once on keyup (A329)', async () => {
    const onDrag = vi.fn()
    const onDragEnd = vi.fn()
    const { container } = await render(<ColumnResize ariaLabel="resize" value={300} min={180} max={420} onDrag={onDrag} onDragEnd={onDragEnd} />)
    const handle = container.querySelector('[role="separator"]')!
    keyEvent(handle, 'keydown', 'ArrowRight')
    keyEvent(handle, 'keydown', 'ArrowRight', true)
    keyEvent(handle, 'keydown', 'ArrowRight', true)
    expect(onDrag.mock.calls).toEqual([[8], [8], [8]])
    expect(onDragEnd).not.toHaveBeenCalled()
    keyEvent(handle, 'keyup', 'ArrowRight')
    expect(onDragEnd).toHaveBeenCalledTimes(1)
    // A stray extra keyup must not fire a second end.
    keyEvent(handle, 'keyup', 'ArrowRight')
    expect(onDragEnd).toHaveBeenCalledTimes(1)
  })

  it('stops listening on pointercancel and releases capture', async () => {
    const onDrag = vi.fn()
    const { container } = await render(<ColumnResize ariaLabel="resize" value={300} min={180} max={420} onDrag={onDrag} />)
    const handle = container.querySelector('[role="separator"]') as HTMLDivElement
    // jsdom lacks pointer-capture APIs; stub them so the cleanup path is testable.
    const release = vi.fn()
    const hasCap = vi.fn(() => true)
    Object.defineProperty(handle, 'setPointerCapture', { configurable: true, value: vi.fn() })
    Object.defineProperty(handle, 'releasePointerCapture', { configurable: true, value: release })
    Object.defineProperty(handle, 'hasPointerCapture', { configurable: true, value: hasCap })

    act(() => {
      handle.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 100, pointerId: 7 }))
    })
    act(() => {
      window.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 120, pointerId: 7 }))
    })
    expect(onDrag).toHaveBeenCalledWith(20)
    act(() => {
      window.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerId: 7 }))
    })
    onDrag.mockClear()
    act(() => {
      window.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 140, pointerId: 7 }))
    })
    expect(onDrag).not.toHaveBeenCalled()
    expect(hasCap).toHaveBeenCalledWith(7)
    expect(release).toHaveBeenCalledWith(7)
  })

  it('calls onDragEnd when drag completes or cancel occurs', async () => {
    const onDrag = vi.fn()
    const onDragEnd = vi.fn()
    const { container } = await render(<ColumnResize ariaLabel="resize" value={300} min={180} max={420} onDrag={onDrag} onDragEnd={onDragEnd} />)
    const handle = container.querySelector('[role="separator"]') as HTMLDivElement
    Object.defineProperty(handle, 'setPointerCapture', { configurable: true, value: vi.fn() })
    Object.defineProperty(handle, 'releasePointerCapture', { configurable: true, value: vi.fn() })

    act(() => {
      handle.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 50, pointerId: 1 }))
    })
    act(() => {
      window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }))
    })
    expect(onDragEnd).toHaveBeenCalledTimes(1)
  })

  it('removes the drag listeners when unmounted mid-drag (F3)', async () => {
    const onDrag = vi.fn()
    const onDragEnd = vi.fn()
    const { container, unmount } = await render(<ColumnResize ariaLabel="resize" value={300} min={180} max={420} onDrag={onDrag} onDragEnd={onDragEnd} />)
    const handle = container.querySelector('[role="separator"]') as HTMLDivElement
    Object.defineProperty(handle, 'setPointerCapture', { configurable: true, value: vi.fn() })
    Object.defineProperty(handle, 'releasePointerCapture', { configurable: true, value: vi.fn() })
    Object.defineProperty(handle, 'hasPointerCapture', { configurable: true, value: vi.fn(() => false) })

    act(() => {
      handle.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 100, pointerId: 3 }))
    })
    act(() => {
      window.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 110, pointerId: 3 }))
    })
    expect(onDrag).toHaveBeenCalledWith(10)

    unmount()
    expect(onDragEnd).toHaveBeenCalledTimes(1)
    onDrag.mockClear()
    act(() => {
      window.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 160, pointerId: 3 }))
      window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 3 }))
    })
    expect(onDrag).not.toHaveBeenCalled()
    expect(onDragEnd).toHaveBeenCalledTimes(1)
  })
})

