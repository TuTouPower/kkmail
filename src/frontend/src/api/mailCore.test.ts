import { describe, expect, it } from 'vitest'
import { mailCoreToMailDetail, mailCoreToMailItem, type MailCoreMessage, type MailCoreMessageDetail } from './mailCore'

describe('mailCoreToMailItem', () => {
  it('maps inbox row to MailItem', () => {
    const row: MailCoreMessage = {
      id: 'uuid-1',
      account_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      account_email: 'box@ex.com',
      subject: 'Hi',
      from_address: 'a@b.c',
      from_name: 'Ann',
      sort_time: '2024-01-01T00:00:00Z',
      is_read: false,
      is_flagged: true,
      has_attachments: true,
      snippet: 'preview',
      body_preview: '',
      folder_id: 'f1',
      locations: [{ folder_id: 'f1', role: 'inbox' }],
    }
    const item = mailCoreToMailItem(row)
    expect(item.id).toBe('uuid-1')
    expect(item.from).toContain('Ann')
    expect(item.accountEmail).toBe('box@ex.com')
    expect(item.accountId).toBe('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
    expect(item.is_flagged).toBe(true)
    expect(item.has_attachments).toBe(true)
    expect(item.folder).toBe('f1')
    expect(item.locations).toEqual([{ folder_id: 'f1', role: 'inbox' }])
    expect(item.accountEmail).not.toBe(item.accountId)
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
      to_addresses: [{ name: 'Doe, Jane', address: 'jane@example.test' }],
      cc_addresses: [{ name: null, address: null, text: 'malformed recipient' }],
      date: '2024-01-01T00:00:00Z',
      is_read: true,
      is_flagged: false,
      has_attachments: false,
      snippet: null,
      body: '<p>x</p>',
      body_type: 'html',
      parse_error: null,
      is_archived: true,
      archive_state: 'archive_complete',
      archive_has_error: false,
      remote_images_allowed: false,
      can_allow_sender: true,
      attachments: [],
    }
    const out = mailCoreToMailDetail(d)
    expect(out.body_type).toBe('html')
    expect(out.body).toContain('<p>')
    expect(out.parse_error).toBeNull()
    expect(out.fromAddress).toBe('a@b.c')
    expect(out.fromName).toBe('A')
    expect(out.toAddresses).toEqual([{ name: 'Doe, Jane', address: 'jane@example.test', text: null }])
    expect(out.ccAddresses).toEqual([{ name: null, address: null, text: 'malformed recipient' }])
  })

  it('preserves parse_error in MailDetail', () => {
    const d: MailCoreMessageDetail = {
      id: 'm-err',
      account_id: 'a1',
      subject: 'Failed MIME',
      from_address: 'a@b.c',
      from_name: 'A',
      from: 'A <a@b.c>',
      to: 'you@x.com',
      cc: '',
      to_addresses: [],
      cc_addresses: [],
      date: '2024-01-01T00:00:00Z',
      is_read: true,
      is_flagged: false,
      has_attachments: false,
      snippet: 'partial snippet',
      body: '',
      body_type: 'empty',
      parse_error: 'body_decode_failed: UnicodeDecodeError: invalid start byte',
      is_archived: true,
      archive_state: 'archive_complete',
      archive_has_error: false,
      remote_images_allowed: false,
      can_allow_sender: true,
      attachments: [],
    }
    const out = mailCoreToMailDetail(d)
    expect(out.parse_error).toBe('body_decode_failed: UnicodeDecodeError: invalid start byte')
  })

  it('preserves an unknown archive state instead of treating it as archived', () => {
    const d: MailCoreMessageDetail = {
      id: 'm-unknown-archive',
      account_id: 'a1',
      subject: 'Legacy import',
      from_address: 'a@b.c',
      from_name: null,
      from: 'a@b.c',
      to: '',
      cc: '',
      to_addresses: [],
      cc_addresses: [],
      date: null,
      is_read: false,
      is_flagged: false,
      has_attachments: false,
      snippet: null,
      body: '',
      body_type: 'empty',
      parse_error: null,
      is_archived: null,
      archive_state: null,
      archive_has_error: false,
      remote_images_allowed: false,
      can_allow_sender: true,
      attachments: [],
    }
    expect(mailCoreToMailDetail(d).is_archived).toBeNull()
    expect(mailCoreToMailDetail(d).archive_state).toBeNull()
    expect(mailCoreToMailDetail(d).archive_has_error).toBe(false)

    const missing = { ...d }
    delete (missing as Partial<MailCoreMessageDetail>).is_archived
    expect(mailCoreToMailDetail(missing as MailCoreMessageDetail).is_archived).toBeNull()
  })
})

describe('list preview source', () => {
  const row: MailCoreMessage = {
    id: 'm-preview', account_id: 'account', subject: 'subject',
    from_address: 'sender@example.com', from_name: null,
    sort_time: '2026-10-23T00:00:00Z', is_read: false, is_flagged: false,
      has_attachments: false, snippet: null, folder_id: 'folder', locations: [{ folder_id: 'folder', role: 'inbox' }], body_preview: 'Body fallback',
  }
  it('uses existing body preview only when provider snippet is absent', () => {
    expect(mailCoreToMailItem(row).body_preview).toBe('Body fallback')
    expect(mailCoreToMailItem({ ...row, snippet: '' }).body_preview).toBe('Body fallback')
    expect(mailCoreToMailItem({ ...row, snippet: 'Provider original' }).body_preview).toBe('Provider original')
    expect(mailCoreToMailItem({ ...row, body_preview: '' }).body_preview).toBeUndefined()
    expect(row.snippet).toBeNull()
  })
})


describe('plain body preview display boundary', () => {
  const row: MailCoreMessage = {
    id: 'plain', account_id: 'account', subject: '', from_address: 'sender@example.com',
    from_name: null, sort_time: '2026-10-23T00:00:00Z', is_read: false,
    is_flagged: false, has_attachments: false, folder_id: null, locations: [],
    snippet: null, body_preview: 'Use <div> &amp; <support@example.com> literally',
  }
  it('keeps body fallback as plain text while cleaning only provider HTML for display', () => {
    expect(mailCoreToMailItem(row).body_preview).toBe('Use <div> &amp; <support@example.com> literally')
    const html = { ...row, snippet: '<p>Provider &amp; summary</p>' }
    expect(mailCoreToMailItem(html).body_preview).toBe('Provider & summary')
    expect(html.snippet).toBe('<p>Provider &amp; summary</p>')
  })
})
