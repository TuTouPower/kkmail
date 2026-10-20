import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

/** Catches render errors and offers a Chinese reload affordance. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div
        role="alert"
        style={{
          minHeight: '100dvh',
          display: 'grid',
          placeItems: 'center',
          padding: 24,
          background: 'var(--bg, #171819)',
          color: 'var(--text, #e8e8e8)',
          textAlign: 'center',
        }}
      >
        <div style={{ maxWidth: 420 }}>
          <strong style={{ fontSize: 18 }}>页面出错了</strong>
          <p style={{ color: 'var(--muted, #9a9a9a)', margin: '12px 0 20px' }}>
            发生了意外错误。请刷新页面重试；若问题持续，请重启应用。
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              height: 36,
              padding: '0 16px',
              borderRadius: 8,
              border: '1px solid var(--line, #333)',
              background: 'var(--accent, #0879d9)',
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            刷新页面
          </button>
        </div>
      </div>
    )
  }
}
