// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MessageList from './MessageList'
import { useMailStore } from '../store/mailStore'
import { __resetCsrfForTests } from '../api/client'
import { cleanup, click, render, typeInto, waitFor } from '../test/render'

const row = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  account_id: 'acc-1',
  account_email: 'box@x.test',
  subject: `Subject ${id}`,
  from_address: `${id}@sender.test`,
  from_name: `Sender ${id}`,
  sort_time: '2026-10-20T08:00:00Z',
  is_read: false,
  is_flagged: false,
  has_attachments: false,
  snippet: `snippet ${id}`,
  folder_id: 'f1',
  ...over,
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

let calls: string[] = []

beforeEach(() => {
  calls = []
  useMailStore.setState({ view: { type: 'allInbox' }, listFilter: 'all', search: '', selectedIds: [], selectedKey: null })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const u = String(url)
    calls.push(u)
    if (u.startsWith('/api/accounts')) return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
    if (u.startsWith('/api/mail/inbox')) return json({ items: [row('a'), row('b', { is_flagged: true, is_read: true })], next_cursor: null })
    if (u.startsWith('/api/mail/search')) return json({ query: 'zz', items: [row('s')], total: 1, offset: 0, next_offset: null })
    return json({ detail: 'unexpected' }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

const subjects = (c: HTMLElement) => [...c.querySelectorAll('.subject')].map((n) => n.textContent)

describe('<MessageList />', () => {
  it('renders the unified inbox from mail-core', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject a', 'Subject b']))
    expect(container.querySelector('.list-count')?.textContent).toContain('2 封邮件 · 1 封未读')
    expect(calls.some((u) => u.startsWith('/api/mail/inbox?limit=100'))).toBe(true)
  })

  it('flagged filter uses the server-side is_flagged field', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    await click([...container.querySelectorAll('[role=tab]')].find((b) => b.textContent === '已标记') || null)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject b']))
  })

  it('switches to server search once the query is long enough', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    await typeInto(container.querySelector('input[name=search]'), 'zz')
    await waitFor(() => expect(subjects(container)).toEqual(['Subject s']))
    expect(calls.some((u) => u.startsWith('/api/mail/search?q=zz'))).toBe(true)
  })

  it('filters by account UUID when an account is selected', async () => {
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-1', email: 'box@x.test' } })
    await render(<MessageList />)
    await waitFor(() => expect(calls.some((u) => u.includes('account_id=acc-1'))).toBe(true))
  })

  it('message rows are keyboard operable (Enter selects)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const row = container.querySelector('.message-row') as HTMLElement
    expect(row.getAttribute('tabindex')).toBe('0')
    expect(row.getAttribute('role')).toBe('button')
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await waitFor(() => expect(useMailStore.getState().selectedKey).toBe('a'))
  })
})

