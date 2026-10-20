/** Stable UI identity for a message. mail-core message ids are globally unique UUIDs. */

/** True when the row has a usable message id (empty ids must not become React keys). */
export function hasMailId(m: { id?: string | null }): m is { id: string } {
  return typeof m?.id === 'string' && m.id.trim().length > 0
}

/**
 * List / selection key. Requires a non-empty id — callers must filter with `hasMailId`
 * before rendering so empty ids cannot collide under a shared placeholder key.
 */
export function mailKey(m: { id: string }): string {
  const id = typeof m?.id === 'string' ? m.id.trim() : ''
  if (!id) throw new Error('mailKey requires a non-empty message id')
  return id
}
