/** Recipient helpers for reply / reply-all. */

const EMAIL_RE = /[A-Z0-9._%+'-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi

export function extractAddresses(value?: string): string[] {
  return (value || '').match(EMAIL_RE) || []
}

export function replyRecipient(from?: string): string {
  return extractAddresses(from)[0] || ''
}

/** Sender + original To/Cc, de-duplicated, without the replying account itself. */
export function replyAllRecipients(from: string | undefined, others: Array<string | undefined>, self: string): string {
  const seen = new Set<string>()
  const selfKey = self.trim().toLowerCase()
  const out: string[] = []
  for (const addr of [replyRecipient(from), ...others.flatMap(extractAddresses)]) {
    const key = addr.toLowerCase()
    if (!addr || key === selfKey || seen.has(key)) continue
    seen.add(key)
    out.push(addr)
  }
  return out.join(', ')
}
