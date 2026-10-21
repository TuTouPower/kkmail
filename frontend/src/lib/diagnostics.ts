/**
 * Frontend diagnostics and error telemetry ring-buffer.
 *
 * Captures unhandled errors, render failures, and key runtime events without
 * exposing user credentials.
 */

export type DiagnosticLevel = 'info' | 'warn' | 'error'
export type DiagnosticCategory = 'runtime' | 'api' | 'realtime' | 'ui'

export interface DiagnosticEntry {
  id: number
  timestamp: string
  level: DiagnosticLevel
  category: DiagnosticCategory
  message: string
  stack?: string
  context?: Record<string, unknown>
}

const MAX_ENTRIES = 100
let nextId = 1
const buffer: DiagnosticEntry[] = []

function redact(text: string): string {
  return text
    .replace(/\b(bearer)\s+[a-z0-9\-._~+/]+=*/gi, '$1 [REDACTED]')
    .replace(/(password|secret|token|api_key)=([^&\s]+)/gi, '$1=[REDACTED]')
}

export function logDiagnostic(
  level: DiagnosticLevel,
  category: DiagnosticCategory,
  message: string,
  context?: Record<string, unknown>,
  stack?: string,
): void {
  const entry: DiagnosticEntry = {
    id: nextId++,
    timestamp: new Date().toISOString(),
    level,
    category,
    message: redact(message),
    context,
    stack: stack ? redact(stack) : undefined,
  }

  buffer.push(entry)
  if (buffer.length > MAX_ENTRIES) {
    buffer.shift()
  }
}

export function getDiagnosticLogs(): readonly DiagnosticEntry[] {
  return [...buffer]
}

export function clearDiagnosticLogs(): void {
  buffer.length = 0
}

export function exportDiagnosticsAsText(): string {
  const meta = [
    `kkmail frontend diagnostics dump`,
    `Generated: ${new Date().toISOString()}`,
    `User-Agent: ${typeof navigator !== 'undefined' ? navigator.userAgent : 'n/a'}`,
    `Entries: ${buffer.length}`,
    '----------------------------------------',
  ].join('\n')

  const lines = buffer.map((e) => {
    const ctx = e.context ? ` | context=${JSON.stringify(e.context)}` : ''
    const stk = e.stack ? `\n  Stack: ${e.stack}` : ''
    return `[${e.timestamp}] [${e.level.toUpperCase()}] [${e.category}] ${e.message}${ctx}${stk}`
  })

  return `${meta}\n${lines.join('\n')}`
}

/** Install global window error and promise rejection listeners. */
export function initGlobalDiagnostics(): void {
  if (typeof window === 'undefined') return

  window.addEventListener('error', (event) => {
    logDiagnostic(
      'error',
      'runtime',
      event.message || 'Window error',
      { filename: event.filename, lineno: event.lineno, colno: event.colno },
      event.error?.stack,
    )
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    const msg = reason instanceof Error ? reason.message : String(reason)
    const stack = reason instanceof Error ? reason.stack : undefined
    logDiagnostic('error', 'runtime', `Unhandled rejection: ${msg}`, undefined, stack)
  })

  ;(window as unknown as { __kkmail_diagnostics?: object }).__kkmail_diagnostics = {
    getLogs: getDiagnosticLogs,
    exportText: exportDiagnosticsAsText,
    clear: clearDiagnosticLogs,
  }
}
