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

  it('redacts nested secret context before storing and exporting it', () => {
    const context = {
      userId: 'user-123',
      credentials: {
        access_token: 'context-access-secret',
        nested: { refreshToken: 'context-refresh-secret', label: 'preserve' },
      },
      rows: [{ apiKey: 'context-api-secret', safe: 'keep' }],
    }
    const original = JSON.parse(JSON.stringify(context))

    logDiagnostic('warn', 'api', 'provider request', context)

    expect(getDiagnosticLogs()[0].context).toEqual({
      userId: 'user-123',
      credentials: {
        access_token: '[REDACTED]',
        nested: { refreshToken: '[REDACTED]', label: 'preserve' },
      },
      rows: [{ apiKey: '[REDACTED]', safe: 'keep' }],
    })
    expect(context).toEqual(original)

    const exported = exportDiagnosticsAsText()
    expect(exported).not.toContain('context-access-secret')
    expect(exported).not.toContain('context-refresh-secret')
    expect(exported).not.toContain('context-api-secret')
    expect(exported).toContain('"label":"preserve"')
  })

  it('redacts JSON-style secret fields in messages and stacks', () => {
    logDiagnostic(
      'error',
      'api',
      'response {"password": "json-password-secret", "api_key":"json-api-secret"} token: plain-token-secret',
      undefined,
      'Error: {"refresh_token":"stack-refresh-secret"}',
    )

    const entry = getDiagnosticLogs()[0]
    expect(entry.message).not.toContain('json-password-secret')
    expect(entry.message).not.toContain('json-api-secret')
    expect(entry.message).not.toContain('plain-token-secret')
    expect(entry.stack).not.toContain('stack-refresh-secret')
    const exported = exportDiagnosticsAsText()
    expect(exported).not.toContain('json-password-secret')
    expect(exported).not.toContain('json-api-secret')
    expect(exported).not.toContain('plain-token-secret')
    expect(exported).not.toContain('stack-refresh-secret')
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
