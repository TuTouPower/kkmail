// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import {
  logDiagnostic,
  getDiagnosticLogs,
  clearDiagnosticLogs,
  exportDiagnosticsAsText,
  initGlobalDiagnostics,
} from './diagnostics'

describe('diagnostics telemetry', () => {
  beforeEach(() => {
    clearDiagnosticLogs()
  })

  it('records logs with redaction', () => {
    logDiagnostic('info', 'api', 'request to api with bearer ya29.SECRET_TOKEN_VALUE')
    const logs = getDiagnosticLogs()
    expect(logs.length).toBe(1)
    expect(logs[0].message).toContain('bearer [REDACTED]')
    expect(logs[0].message).not.toContain('SECRET_TOKEN_VALUE')
  })

  it('caps buffer at max limit', () => {
    for (let i = 0; i < 120; i++) {
      logDiagnostic('info', 'runtime', `message-${i}`)
    }
    const logs = getDiagnosticLogs()
    expect(logs.length).toBe(100)
    expect(logs[0].message).toBe('message-20')
    expect(logs[99].message).toBe('message-119')
  })

  it('exports formatted text dump', () => {
    logDiagnostic('error', 'ui', 'render crash', { component: 'MessageList' }, 'Error: boom\n  at Component')
    const text = exportDiagnosticsAsText()
    expect(text).toContain('kkmail frontend diagnostics dump')
    expect(text).toContain('[ERROR] [ui] render crash')
    expect(text).toContain('component')
    expect(text).toContain('Stack: Error: boom')
  })

  it('initializes global window listeners without crashing', () => {
    initGlobalDiagnostics()
    expect((window as unknown as { __kkmail_diagnostics?: object }).__kkmail_diagnostics).toBeDefined()
  })
})
