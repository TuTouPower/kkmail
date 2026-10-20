/** Shared helpers for destructive actions and backend result checks. */

export function confirmAction(message: string): boolean {
  return typeof window === 'undefined' ? true : window.confirm(message)
}

/** Readable message for a thrown ApiError / Error / unknown. */
export function errorMessage(err: unknown, fallback = '操作失败'): string {
  if (err && typeof err === 'object' && 'message' in err) {
    const msg = (err as { message?: unknown }).message
    if (typeof msg === 'string' && msg) return msg
    if (msg && typeof msg === 'object' && 'message' in msg) return String((msg as { message: unknown }).message)
  }
  return fallback
}

/**
 * Flask often answers HTTP 200 with { success: false, error }. Turn that into
 * an exception so callers handle it the same way as a network error.
 */
export function ensureSuccess<T>(res: T, fallback = '操作失败'): T {
  if (res && typeof res === 'object' && (res as { success?: unknown }).success === false) {
    const err = (res as { error?: unknown }).error
    const message = typeof err === 'string' ? err : (err as { message?: string } | undefined)?.message || fallback
    throw new Error(message)
  }
  return res
}
