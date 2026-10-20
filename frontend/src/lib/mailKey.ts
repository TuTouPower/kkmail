/** Stable UI identity for a message. mail-core message ids are globally unique UUIDs. */
export function mailKey(m: { id: string }): string {
  return m.id
}
