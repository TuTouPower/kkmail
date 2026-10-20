import { describe, expect, it } from 'vitest'
import { shouldInvalidateMailCoreInbox } from './useMailCoreRealtime'

describe('shouldInvalidateMailCoreInbox', () => {
  it('invalidates on mail / folder stats change events', () => {
    expect(shouldInvalidateMailCoreInbox('message.upserted')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('message.removed')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('folder.stats_updated')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('mail.changed')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('folder.stats.changed')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('client.resync_hint')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('sync.completed')).toBe(true)
  })

  it('ignores progress-only events', () => {
    expect(shouldInvalidateMailCoreInbox('sync.progress')).toBe(false)
    expect(shouldInvalidateMailCoreInbox('message')).toBe(false)
  })
})
