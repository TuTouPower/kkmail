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
