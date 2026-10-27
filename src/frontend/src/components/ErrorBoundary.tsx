import { Component, type ErrorInfo, type ReactNode } from 'react'
import { copyTextToClipboard } from '../lib/clipboard'
import { exportDiagnosticsAsText, logDiagnostic } from '../lib/diagnostics'

/**
 * A354: diagnostic stacks are copied out of the app for troubleshooting,
 * so strip directory structure (home dirs, project layout, drive paths,
 * dev-server URLs) down to the bare file name before a stack is stored.
 * Line/column suffixes stay attached to the file name segment.
 */
export function trimStackPaths(stack: string): string {
  const keepFileName = (token: string): string => {
    const parts = token.split(/[\\/]/).filter(Boolean)
    return parts.length ? parts[parts.length - 1] : token
  }
  return stack
    .replace(/https?:\/\/[^\s)]+/g, keepFileName)
    .replace(/(?:[A-Za-z]:[\\/]|\/)[^\s()]+/g, keepFileName)
}

type Props = {
  children: ReactNode
  inline?: boolean
  fallbackTitle?: string
  resetKey?: string | number | null
}
type State = { error: Error | null; copied: boolean; copyFailed: boolean; resetKey: Props['resetKey'] }

/** Catches render errors and offers a Chinese reload affordance. */
export default class ErrorBoundary extends Component<Props, State> {
  private copyFeedbackTimer: ReturnType<typeof setTimeout> | null = null
  private mounted = false

  constructor(props: Props) {
    super(props)
    this.state = { error: null, copied: false, copyFailed: false, resetKey: props.resetKey }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey !== state.resetKey) {
      return { error: null, copied: false, copyFailed: false, resetKey: props.resetKey }
    }
    return null
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error, copied: false, copyFailed: false }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    logDiagnostic(
      'error',
      'ui',
      error.message || 'React 渲染异常',
      undefined,
      trimStackPaths(`${error.stack || ''}\n${info.componentStack || ''}`),
    )
  }

  componentDidMount() {
    this.mounted = true
  }

  componentDidUpdate(prevProps: Props) {
    if (prevProps.resetKey !== this.props.resetKey) {
      this.clearCopyFeedbackTimer()
    }
  }

  componentWillUnmount() {
    this.mounted = false
    this.clearCopyFeedbackTimer()
  }

  private clearCopyFeedbackTimer() {
    if (this.copyFeedbackTimer !== null) {
      clearTimeout(this.copyFeedbackTimer)
      this.copyFeedbackTimer = null
    }
  }

  private showCopyFeedback(copied: boolean) {
    if (!this.mounted) return
    this.clearCopyFeedbackTimer()
    this.setState({ copied, copyFailed: !copied })
    this.copyFeedbackTimer = setTimeout(() => {
      this.copyFeedbackTimer = null
      this.setState({ copied: false, copyFailed: false })
    }, 2000)
  }

  copyReport = async () => {
    try {
      await copyTextToClipboard(exportDiagnosticsAsText())
      this.showCopyFeedback(true)
    } catch {
      this.showCopyFeedback(false)
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    const isInline = Boolean(this.props.inline)
    return (
      <div
        role="alert"
        style={
          isInline
            ? {
                height: '100%',
                minHeight: 180,
                display: 'grid',
                placeItems: 'center',
                padding: 16,
                background: 'var(--surface-2)',
                color: 'var(--text)',
                textAlign: 'center',
                boxSizing: 'border-box',
              }
            : {
                minHeight: '100dvh',
                display: 'grid',
                placeItems: 'center',
                padding: 24,
                background: 'var(--canvas)',
                color: 'var(--text)',
                textAlign: 'center',
              }
        }
      >
        <div style={{ maxWidth: 420 }}>
          <strong style={{ fontSize: isInline ? 15 : 18 }}>{this.props.fallbackTitle || '页面出错了'}</strong>
          <p style={{ color: 'var(--muted)', margin: '12px 0 20px', fontSize: isInline ? 13 : 14 }}>
            {isInline
              ? '该模块发生意外错误。可重试或复制诊断日志排查。'
              : '发生了意外错误。请刷新页面重试；若问题持续，可复制诊断日志排查。'}
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
            <button
              type="button"
              onClick={() => {
                if (isInline) {
                  this.clearCopyFeedbackTimer()
                  this.setState({ error: null, copied: false, copyFailed: false })
                } else {
                  window.location.reload()
                }
              }}
              style={{
                height: isInline ? 32 : 36,
                padding: '0 16px',
                borderRadius: 8,
                border: '1px solid var(--line)',
                background: 'var(--primary)',
                color: 'var(--on-primary)',
                cursor: 'pointer',
                fontSize: isInline ? 13 : 14,
              }}
            >
              {isInline ? '重试模块' : '刷新页面'}
            </button>
            <button
              type="button"
              onClick={this.copyReport}
              style={{
                height: isInline ? 32 : 36,
                padding: '0 16px',
                borderRadius: 8,
                border: '1px solid var(--line)',
                background: 'transparent',
                color: this.state.copyFailed ? 'var(--red)' : 'var(--text)',
                cursor: 'pointer',
                fontSize: isInline ? 13 : 14,
              }}
            >
              {this.state.copied
                ? '已复制日志'
                : this.state.copyFailed
                  ? '复制失败'
                  : '复制诊断日志'}
            </button>
          </div>
          <p style={{ color: 'var(--muted)', margin: '12px 0 0', fontSize: 12 }}>
            诊断日志包含错误堆栈等技术细节，请仅发送给可信的排查人员。
          </p>
        </div>
      </div>
    )
  }
}

