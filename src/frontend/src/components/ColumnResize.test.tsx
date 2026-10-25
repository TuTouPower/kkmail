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
})

