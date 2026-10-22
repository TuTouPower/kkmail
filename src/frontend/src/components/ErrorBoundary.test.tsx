// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ErrorBoundary from './ErrorBoundary'
import { cleanup, click, render, waitFor } from '../test/render'

function BuggyComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test render crash')
  }
  return <div>Normal Content</div>
}

describe('<ErrorBoundary />', () => {
  let consoleSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleSpy.mockRestore()
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders children when no error occurs', async () => {
    const { container } = await render(
      <ErrorBoundary>
        <BuggyComponent shouldThrow={false} />
      </ErrorBoundary>,
    )
    expect(container.textContent).toContain('Normal Content')
  })

  it('catches crash and shows copied status on successful clipboard write', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })

    const { container } = await render(
      <ErrorBoundary>
        <BuggyComponent shouldThrow={true} />
      </ErrorBoundary>,
    )

    expect(container.textContent).toContain('页面出错了')
    const copyBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '复制诊断日志')
    expect(copyBtn).not.toBeNull()

    await click(copyBtn!)
    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalled()
      expect(copyBtn!.textContent).toBe('已复制日志')
    })
  })

  it('catches crash and shows failure status when clipboard rejects', async () => {
    const writeTextMock = vi.fn().mockRejectedValue(new Error('Permission denied'))
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    })

    const { container } = await render(
      <ErrorBoundary>
        <BuggyComponent shouldThrow={true} />
      </ErrorBoundary>,
    )

    const copyBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '复制诊断日志')
    await click(copyBtn!)

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalled()
      expect(copyBtn!.textContent).toBe('复制失败')
    })
  })

  it('shows failure status when clipboard is missing', async () => {
    // navigator.clipboard is undefined
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
    })

    const { container } = await render(
      <ErrorBoundary>
        <BuggyComponent shouldThrow={true} />
      </ErrorBoundary>,
    )

    const copyBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '复制诊断日志')
    await click(copyBtn!)

    await waitFor(() => {
      expect(copyBtn!.textContent).toBe('复制失败')
    })
  })
})
