// @vitest-environment jsdom
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ErrorBoundary from './ErrorBoundary'
import { cleanup, click, render, waitFor } from '../test/render'
import { clearDiagnosticLogs, getDiagnosticLogs } from '../lib/diagnostics'

function PathStackBuggy(): never {
  const err = new Error('crash with path')
  err.stack = 'Error: crash with path\n'
    + '    at Buggy (/home/alice/private-project/src/components/Buggy.tsx:12:34)\n'
    + '    at render (C:\\Users\\alice\\project\\src\\main.tsx:3:5)'
  throw err
}

function BuggyComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test render crash')
  }
  return <div>Normal Content</div>
}

function RecoverableBoundary() {
  const [resetKey, setResetKey] = useState(0)
  const [shouldThrow, setShouldThrow] = useState(true)
  return (
    <>
      <button type="button" onClick={() => { setShouldThrow(false); setResetKey(1) }}>切换视图</button>
      <ErrorBoundary resetKey={resetKey}>
        <BuggyComponent shouldThrow={shouldThrow} />
      </ErrorBoundary>
    </>
  )
}

describe('<ErrorBoundary />', () => {
  let consoleSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleSpy.mockRestore()
    cleanup()
    vi.useRealTimers()
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

  it('shows copied status when navigator.clipboard is missing but execCommand succeeds', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
    })
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    const { container } = await render(
      <ErrorBoundary>
        <BuggyComponent shouldThrow={true} />
      </ErrorBoundary>,
    )

    const copyBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '复制诊断日志')
    await click(copyBtn!)

    await waitFor(() => {
      expect(execCommand).toHaveBeenCalledWith('copy')
      expect(copyBtn!.textContent).toBe('已复制日志')
    })
  })

  it('clears the copy feedback timer when unmounted', async () => {
    vi.useFakeTimers()
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout')
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')
    const { container } = await render(
      <ErrorBoundary>
        <BuggyComponent shouldThrow />
      </ErrorBoundary>,
    )

    const copyBtn = [...container.querySelectorAll('button')].find((button) => button.textContent === '复制诊断日志')
    await click(copyBtn!)
    const timerIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 2000)
    expect(timerIndex).toBeGreaterThanOrEqual(0)
    const timerId = setTimeoutSpy.mock.results[timerIndex].value

    cleanup()
    expect(clearTimeoutSpy).toHaveBeenCalledWith(timerId)
  })

  it('trims filesystem paths from the stored diagnostic stack and warns the log contains technical details (A354)', async () => {
    clearDiagnosticLogs()
    const { container } = await render(
      <ErrorBoundary>
        <PathStackBuggy />
      </ErrorBoundary>,
    )
    expect(container.textContent).toContain('页面出错了')
    const entry = getDiagnosticLogs().find((e) => e.message === 'crash with path')
    expect(entry).toBeTruthy()
    expect(entry!.stack).not.toContain('/home/alice')
    expect(entry!.stack).not.toContain('private-project')
    expect(entry!.stack).not.toContain('Users\\alice')
    expect(entry!.stack).toContain('Buggy.tsx:12:34')
    expect(entry!.stack).toContain('main.tsx:3:5')
    // The copy affordance must warn that the log carries technical details.
    expect(container.textContent).toContain('技术细节')
  })

  it('resets a caught error when resetKey changes', async () => {
    const { container } = await render(<RecoverableBoundary />)
    expect(container.textContent).toContain('页面出错了')

    await click(container.querySelector('button'))

    expect(container.textContent).toContain('Normal Content')
    expect(container.textContent).not.toContain('页面出错了')
  })
})
