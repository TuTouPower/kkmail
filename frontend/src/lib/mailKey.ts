/**
 * Stable identity for a message in the UI. IMAP UIDs are only unique per folder
 * (and Graph ids per mailbox), so the key must include account and folder.
 */
export function mailKey(m: { accountEmail: string; folder?: string; id: string }, fallbackFolder = 'inbox'): string {
  return [m.accountEmail.toLowerCase(), m.folder || fallbackFolder, m.id].join('\u001f')
}
