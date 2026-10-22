import { Component, type ErrorInfo, type ReactNode } from 'react'
import { exportDiagnosticsAsText, logDiagnostic } from '../lib/diagnostics'

type Props = {
  children: ReactNode
  inline?: boolean
  fallbackTitle?: string
}
type State = { error: Error | null; copied: boolean; copyFailed: boolean }

/** Catches render errors and offers a Chinese reload affordance. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, copied: false, copyFailed: false }

  static getDerivedStateFromError(error: Error): State {
    return { error, copied: false, copyFailed: false }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    logDiagnostic(
      'error',
      'ui',
      error.message || 'React 渲染异常',
      undefined,
      `${error.stack || ''}\n${info.componentStack || ''}`,
    )
  }

  copyReport = async () => {
    try {
      if (!navigator?.clipboard?.writeText) {
        throw new Error('剪贴板不可用')
      }
      await navigator.clipboard.writeText(exportDiagnosticsAsText())
      this.setState({ copied: true, copyFailed: false })
      setTimeout(() => this.setState({ copied: false }), 2000)
    } catch {
      this.setState({ copied: false, copyFailed: true })
      setTimeout(() => this.setState({ copyFailed: false }), 2000)
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
                  this.setState({ error: null })
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
        </div>
      </div>
    )
  }
}

