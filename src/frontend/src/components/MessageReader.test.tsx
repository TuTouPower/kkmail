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
  it('renders the text body and attachment links by UUID with formatted size', async () => {
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.querySelector('.email-body-text')?.textContent).toBe('plain body text'))
    const link = container.querySelector('.attachment-list a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/api/mail/attachments/att-1')
    expect(link.getAttribute('download')).toBe('r.pdf')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.querySelector('small')?.textContent).toBe('10 B')
  })

  // 旧测试 "has no compose/send actions" 已删除：t003 演进为支持占位展示发信按钮并设为 disabled 禁用状态
  it('renders disabled placeholder actions for compose/reply/forward (AC-003)', async () => {
    const { container } = await render(<MessageReader />)
    const replyBtn = container.querySelector('[aria-label=回复]') as HTMLButtonElement
    const replyAllBtn = container.querySelector('[aria-label=回复所有人]') as HTMLButtonElement
    const forwardBtn = container.querySelector('[aria-label=转发]') as HTMLButtonElement
    expect(replyBtn).not.toBeNull()
    expect(replyBtn.disabled).toBe(true)
    expect(replyAllBtn).not.toBeNull()
    expect(replyAllBtn.disabled).toBe(true)
    expect(forwardBtn).not.toBeNull()
    expect(forwardBtn.disabled).toBe(true)
  })

  it('toggles read/unread status on the same button based on current state (AC-002)', async () => {
    const { container } = await render(<MessageReader />)
    // item is_read is true initially -> button should be "标为未读" and clickable
    const unreadBtn = container.querySelector('[aria-label=标为未读]') as HTMLButtonElement
    expect(unreadBtn).not.toBeNull()
    expect(unreadBtn.disabled).toBe(false)

    await click(unreadBtn)
    await waitFor(() => expect(posts).toContainEqual({ url: '/api/mail/messages/m-1/read', body: { is_read: false } }))
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(false)

    // After state becomes unread -> button should switch to "标为已读"
    await waitFor(() => expect(container.querySelector('[aria-label=标为已读]')).not.toBeNull())
    const markReadBtn = container.querySelector('[aria-label=标为已读]') as HTMLButtonElement
    await click(markReadBtn)
    await waitFor(() => expect(posts).toContainEqual({ url: '/api/mail/messages/m-1/read', body: { is_read: true } }))
  })

  it('flag button posts is_flagged=true and updates the cached row', async () => {
    const { container } = await render(<MessageReader />)
    await click(container.querySelector('[aria-label=标记邮件]'))
    await waitFor(() => expect(posts).toEqual([{ url: '/api/mail/messages/m-1/flag', body: { is_flagged: true } }]))
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_flagged).toBe(true)
    await waitFor(() => expect(container.querySelector('[aria-label=取消标记]')).not.toBeNull())
  })
})
