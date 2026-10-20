/** Recipient helpers for reply / reply-all and Graph send. */

const EMAIL_RE = /[A-Z0-9._%+'-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi
const SEND_ADDRESS_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Split To/Cc text into the string array `/api/outlook/send-mail` requires. */
export function parseSendRecipients(value?: string): { recipients: string[]; error: string } {
  const raw = String(value || '').split(/[,;\n，；]+/).map((part) => part.trim()).filter(Boolean)
  if (!raw.length) return { recipients: [], error: '请至少填写一个收件人' }
  const recipients: string[] = []
  const seen = new Set<string>()
  for (const part of raw) {
    if (!SEND_ADDRESS_RE.test(part)) return { recipients: [], error: '请填写有效的收件人邮箱地址' }
    const key = part.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    recipients.push(key)
  }
  return { recipients, error: '' }
}

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
