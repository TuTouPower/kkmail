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
    const { container } = await render(<ColumnResize ariaLabel="调整列宽" onDrag={() => {}} />)
    const handle = container.querySelector('[role="separator"]')
    expect(handle).not.toBeNull()
    expect(handle?.getAttribute('aria-orientation')).toBe('vertical')
    expect(handle?.getAttribute('aria-label')).toBe('调整列宽')
    expect(handle?.getAttribute('tabindex')).toBe('0')
  })

  it('arrow keys resize by 8px steps and other keys are ignored', async () => {
    const onDrag = vi.fn()
    const { container } = await render(<ColumnResize ariaLabel="resize" onDrag={onDrag} />)
    const handle = container.querySelector('[role="separator"]')!
    key(handle, 'ArrowLeft')
    key(handle, 'ArrowRight')
    key(handle, 'ArrowRight')
    key(handle, 'Enter')
    expect(onDrag.mock.calls).toEqual([[-8], [8], [8]])
  })
})
