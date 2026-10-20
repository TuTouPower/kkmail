import { describe, expect, it } from 'vitest'
import { mailCoreToMailDetail, mailCoreToMailItem, type MailCoreMessage, type MailCoreMessageDetail } from './mailCore'

describe('mailCoreToMailItem', () => {
  it('maps inbox row to MailItem', () => {
    const row: MailCoreMessage = {
      id: 'uuid-1',
      account_id: 'acc-1',
      subject: 'Hi',
      from_address: 'a@b.c',
      from_name: 'Ann',
      sort_time: '2024-01-01T00:00:00Z',
      is_read: false,
      has_attachments: true,
      snippet: 'preview',
      folder_id: 'f1',
    }
    const item = mailCoreToMailItem(row)
    expect(item.id).toBe('uuid-1')
    expect(item.from).toContain('Ann')
    expect(item.accountEmail).toBe('acc-1')
    expect(item.id_mode).toBe('mail_core')
    expect(item.has_attachments).toBe(true)
  })
})

describe('mailCoreToMailDetail', () => {
  it('maps detail and prefers html body_type', () => {
    const d: MailCoreMessageDetail = {
      id: 'm1',
      account_id: 'a1',
      subject: 'S',
      from_address: 'a@b.c',
      from_name: 'A',
      from: 'A <a@b.c>',
      to: 'you@x.com',
      cc: '',
      date: '2024-01-01T00:00:00Z',
      is_read: true,
      has_attachments: false,
      snippet: null,
      body: '<p>x</p>',
      body_type: 'html',
      parse_error: null,
      attachments: [],
    }
    const out = mailCoreToMailDetail(d)
    expect(out.body_type).toBe('html')
    expect(out.body).toContain('<p>')
  })
})
