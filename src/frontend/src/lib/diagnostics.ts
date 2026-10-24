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
const SENSITIVE_KEY_PATTERN = /(?:password|secret|token|api[_-]?key|authorization|cookie)/i
const SENSITIVE_ASSIGNMENT_PATTERN =
  /((?:["']?[a-z0-9_-]*(?:password|secret|token|api[_-]?key|authorization|cookie)[a-z0-9_-]*["']?)\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^&\s,}\]]+)/gi

function redact(text: string): string {
  return text
    .replace(/\b(bearer)\s+[a-z0-9\-._~+/]+=*/gi, '$1 [REDACTED]')
    .replace(SENSITIVE_ASSIGNMENT_PATTERN, (_match, prefix: string, value: string) => {
      const quote = value.startsWith('"') || value.startsWith("'") ? value[0] : ''
      return `${prefix}${quote}[REDACTED]${quote}`
    })
}

function redactContextValue(value: unknown): unknown {
  if (typeof value === 'string') return redact(value)
  if (Array.isArray(value)) return value.map(redactContextValue)
  if (value instanceof Date) return value

  if (value !== null && typeof value === 'object') {
    const redacted: Record<string, unknown> = {}
    for (const [key, child] of Object.entries(value)) {
      redacted[key] = SENSITIVE_KEY_PATTERN.test(key) ? '[REDACTED]' : redactContextValue(child)
    }
    return redacted
  }

  return value
}

function redactContext(context: Record<string, unknown>): Record<string, unknown> {
  return redactContextValue(context) as Record<string, unknown>
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
    context: context ? redactContext(context) : undefined,
    stack: stack ? redact(stack) : undefined,
  }

  buffer.push(entry)
  if (buffer.length > MAX_ENTRIES) {
    buffer.shift()
  }
}

export function getDiagnosticLogs(): readonly DiagnosticEntry[] {
  return buffer.map((entry) => ({
    ...entry,
    message: redact(entry.message),
    context: entry.context ? redactContext(entry.context) : undefined,
    stack: entry.stack ? redact(entry.stack) : undefined,
  }))
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
    const ctx = e.context ? ` | context=${JSON.stringify(redactContext(e.context))}` : ''
    const stk = e.stack ? `\n  Stack: ${redact(e.stack)}` : ''
    return `[${e.timestamp}] [${e.level.toUpperCase()}] [${e.category}] ${redact(e.message)}${ctx}${stk}`
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
