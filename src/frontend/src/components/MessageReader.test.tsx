// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MessageReader from './MessageReader'
import { useMailStore } from '../store/mailStore'
import { __resetCsrfForTests } from '../api/client'
import { ALL_ACCOUNTS, queryClient, queryKeys, type MailItem } from '../api/queries'
import { cleanup, click, render, waitFor } from '../test/render'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const item: MailItem = {
  id: 'm-1',
  subject: 'Quarterly report',
  from: 'Ann <ann@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: true,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const posts: Array<{ url: string; body: unknown }> = []

beforeEach(() => {
  posts.length = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const u = String(url)
    if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
    if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
    if (u === '/api/mail/messages/m-1') {
      return json({
        id: 'm-1', account_id: 'acc-1', subject: 'Quarterly report', from_address: 'ann@x.test', from_name: 'Ann',
        from: 'Ann <ann@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T08:00:00Z', is_read: true,
        is_flagged: false, has_attachments: true, snippet: null, body: 'plain body text', body_type: 'text',
        parse_error: null, attachments: [{ id: 'att-1', name: 'r.pdf', contentType: 'application/pdf', size: 10, is_inline: false }],
      })
    }
    if (init.method === 'POST') {
      posts.push({ url: u, body: JSON.parse(String(init.body)) })
      return json({ id: 'm-1', account_id: 'acc-1', operation_id: 'op', is_flagged: true, success: true })
    }
    return json({ detail: 'unexpected' }, 404)
  }))
  queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item])
  useMailStore.setState({ selectedKey: 'm-1' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

describe('<MessageReader />', () => {
  it('renders the text body and attachment links by UUID', async () => {
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.querySelector('.email-body-text')?.textContent).toBe('plain body text'))
    const link = container.querySelector('.attachment-list a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/api/mail/attachments/att-1')
  })

  it('has no compose/send actions (send is out of scope)', async () => {
    const { container } = await render(<MessageReader />)
    expect(container.querySelector('[aria-label=回复]')).toBeNull()
    expect(container.querySelector('[aria-label=转发]')).toBeNull()
  })

  it('flag button posts is_flagged=true and updates the cached row', async () => {
    const { container } = await render(<MessageReader />)
    await click(container.querySelector('[aria-label=标记邮件]'))
    await waitFor(() => expect(posts).toEqual([{ url: '/api/mail/messages/m-1/flag', body: { is_flagged: true } }]))
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_flagged).toBe(true)
    await waitFor(() => expect(container.querySelector('[aria-label=取消标记]')).not.toBeNull())
  })
})
