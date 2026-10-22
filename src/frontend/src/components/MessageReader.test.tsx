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

const htmlItemWithImages: MailItem = {
  id: 'm-2',
  subject: 'Html with remote image',
  from: 'Bob <bob@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const htmlItemOther: MailItem = {
  id: 'm-3',
  subject: 'Second html with remote image',
  from: 'Carol <carol@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const htmlItemLightRich: MailItem = {
  id: 'm-4',
  subject: 'Light rich newsletter',
  from: 'Daily <news@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: false,
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
    if (u === '/api/mail/messages/m-2') {
      return json({
        id: 'm-2', account_id: 'acc-1', subject: 'Html with remote image', from_address: 'bob@x.test', from_name: 'Bob',
        from: 'Bob <bob@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T09:00:00Z', is_read: true,
        is_flagged: false, has_attachments: false, snippet: null,
        body: '<p>Remote image mail</p><img src="https://tracker.test/pixel.png">', body_type: 'html',
        parse_error: null, attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-3') {
      return json({
        id: 'm-3', account_id: 'acc-1', subject: 'Second html with remote image', from_address: 'carol@x.test', from_name: 'Carol',
        from: 'Carol <carol@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T10:00:00Z', is_read: true,
        is_flagged: false, has_attachments: false, snippet: null,
        body: '<p>Another remote image</p><img src="https://tracker.test/other.png">', body_type: 'html',
        parse_error: null, attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-4') {
      return json({
        id: 'm-4', account_id: 'acc-1', subject: 'Light rich newsletter', from_address: 'news@x.test', from_name: 'Daily',
        from: 'Daily <news@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T11:00:00Z', is_read: true,
        is_flagged: false, has_attachments: false, snippet: null,
        body: '<div style="background-color: #ffffff; color: #111111;"><p>Rich article</p></div>', body_type: 'html',
        parse_error: null, attachments: [],
      })
    }
    if (init.method === 'POST') {
      posts.push({ url: u, body: JSON.parse(String(init.body)) })
      return json({ id: 'm-1', account_id: 'acc-1', operation_id: 'op', is_flagged: true, success: true })
    }
    return json({ detail: 'unexpected' }, 404)
  }))
  queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item, htmlItemWithImages, htmlItemOther, htmlItemLightRich])
  useMailStore.setState({ selectedKey: 'm-1', theme: 'dark' })
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

  it('blocks remote images by default, allows only current message when opted in, and re-blocks on message switch (AC-004, AC-005)', async () => {
    useMailStore.setState({ selectedKey: 'm-2' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => expect(container.textContent).toContain('远程图片已拦截（防追踪）'))
    let iframe = container.querySelector('iframe.email-body-frame') as HTMLIFrameElement
    expect(iframe).not.toBeNull()
    expect(iframe.srcdoc).toContain("default-src 'none'")
    expect(iframe.srcdoc).not.toContain('img-src https:')

    const allowBtn = Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.includes('仅此邮件允许加载'))
    expect(allowBtn).toBeDefined()
    await click(allowBtn!)

    await waitFor(() => {
      const updatedIframe = container.querySelector('iframe.email-body-frame') as HTMLIFrameElement
      expect(updatedIframe.srcdoc).toContain('img-src https:')
    })
    expect(container.textContent).not.toContain('远程图片已拦截（防追踪）')

    useMailStore.setState({ selectedKey: 'm-3' })
    await waitFor(() => expect(container.textContent).toContain('远程图片已拦截（防追踪）'))
    iframe = container.querySelector('iframe.email-body-frame') as HTMLIFrameElement
    expect(iframe.srcdoc).not.toContain('img-src https:')
  })

  it('renders explicit fixed-light html inside an isolated white paper card in dark mode (AC-003)', async () => {
    useMailStore.setState({ selectedKey: 'm-4', theme: 'dark' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => expect(container.querySelector('.mail-paper-card')).not.toBeNull())
    const paperCard = container.querySelector('.mail-paper-card') as HTMLDivElement
    expect(paperCard.getAttribute('style')).toContain('background: rgb(255, 255, 255)')
    const iframe = paperCard.querySelector('iframe.email-body-frame') as HTMLIFrameElement
    expect(iframe).not.toBeNull()
    expect(iframe.srcdoc).toContain('background:#ffffff')

    // Switch theme to light: paper card is not used in light mode, background updates
    useMailStore.setState({ theme: 'light' })
    await waitFor(() => expect(container.querySelector('.mail-paper-card')).toBeNull())
    const lightIframe = container.querySelector('iframe.email-body-frame') as HTMLIFrameElement
    expect(lightIframe.srcdoc).toContain('background:#ffffff')
  })
})
