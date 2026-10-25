/** Shared helpers for destructive actions and backend result checks. */

export function confirmAction(message: string): boolean {
  return typeof window === 'undefined' ? true : window.confirm(message)
}

const OBJECT_PLACEHOLDER = '[object Object]'

/**
 * Extract a human-readable string from an unknown error payload fragment.
 * Handles plain strings, FastAPI-style nested `detail` values (object or
 * array), `{error}` / `{message}` / `{msg}` objects, and rejects the useless
 * "[object Object]" placeholder produced by naive String(object) coercion.
 */
function readableText(value: unknown, depth = 0): string | null {
  if (depth > 5 || value == null) return null
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed || trimmed === OBJECT_PLACEHOLDER) return null
    return value
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const parts = value.map((item) => readableText(item, depth + 1)).filter((part): part is string => !!part)
    return parts.length ? parts.join('; ') : null
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    for (const key of ['message', 'error', 'msg', 'detail']) {
      const text = readableText(record[key], depth + 1)
      if (text) return text
    }
  }
  return null
}

/** Readable message for a thrown ApiError / Error / unknown. */
export function errorMessage(err: unknown, fallback = '操作失败'): string {
  if (typeof err === 'string') return readableText(err) ?? fallback
  if (err && typeof err === 'object') {
    const record = err as Record<string, unknown>
    // ApiError / Error carry `message`; backend failures may only carry a
    // nested `detail` (string, object, or validation-error array).
    for (const key of ['message', 'detail', 'error']) {
      const text = readableText(record[key])
      if (text) return text
    }
    const text = readableText(err)
    if (text) return text
  }
  return fallback
}
