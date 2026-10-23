// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
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

const failedItem: MailItem = {
  id: 'm-failed',
  subject: 'Corrupted MIME Email',
  from: 'Bad <bad@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const failedItemWithSnippet: MailItem = {
  id: 'm-failed-snippet',
  subject: 'Failed MIME with Snippet',
  from: 'Bad2 <bad2@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: false,
  body_preview: 'Metadata snippet preview',
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const emptyNormalItem: MailItem = {
  id: 'm-empty',
  subject: 'Legitimate Empty Email',
  from: 'Empty <empty@x.test>',
  is_read: true,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const unarchivedItem: MailItem = {
  id: 'm-unarchived',
  subject: 'Unarchived Email',
  from: 'Unarchived <u@x.test>',
  is_read: false,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const syncFailedItem: MailItem = {
  id: 'm-sync-failed',
  subject: 'Sync Failed Email',
  from: 'Fail <f@x.test>',
  is_read: false,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'box@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
}

const posts: Array<{ url: string; body: unknown }> = []
const nullDateItem = { ...item, id: 'm-null-date', date: '2026-10-20T08:00:00Z' }

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
    if (u === '/api/mail/messages/m-null-date') {
      return json({
        id: 'm-null-date', account_id: 'acc-1', subject: 'Unknown received time', from_address: 'ann@x.test', from_name: 'Ann',
        from: 'Ann <ann@x.test>', to: 'box@x.test', cc: '', date: null, is_read: true,
        is_flagged: false, has_attachments: false, snippet: null, body: 'plain body text', body_type: 'text',
        parse_error: null, attachments: [],
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
    if (u === '/api/mail/messages/m-failed') {
      return json({
        id: 'm-failed', account_id: 'acc-1', subject: 'Corrupted MIME Email', from_address: 'bad@x.test', from_name: 'Bad',
        from: 'Bad <bad@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T12:00:00Z', is_read: true,
        is_flagged: false, has_attachments: false, snippet: null,
        body: '', body_type: 'empty',
        parse_error: 'body_decode_failed: UnicodeDecodeError: invalid start byte', attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-failed-snippet') {
      return json({
        id: 'm-failed-snippet', account_id: 'acc-1', subject: 'Failed MIME with Snippet', from_address: 'bad2@x.test', from_name: 'Bad2',
        from: 'Bad2 <bad2@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T13:00:00Z', is_read: true,
        is_flagged: false, has_attachments: false, snippet: 'Metadata snippet preview',
        body: '', body_type: 'empty',
        parse_error: 'header_defect in From: UndecodableBytesDefect', attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-empty') {
      return json({
        id: 'm-empty', account_id: 'acc-1', subject: 'Legitimate Empty Email', from_address: 'empty@x.test', from_name: 'Empty',
        from: 'Empty <empty@x.test>', to: 'box@x.test', cc: '', date: '2026-10-20T14:00:00Z', is_read: true,
        is_flagged: false, has_attachments: false, snippet: null,
        body: '', body_type: 'empty',
        parse_error: null, attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-unarchived') {
      return json({
        id: 'm-unarchived', account_id: 'acc-1', subject: 'Unarchived Email', from_address: 'u@x.test', from_name: 'Unarchived',
        from: 'Unarchived <u@x.test>', to: 'box@x.test', cc: '', date: '2018-10-26T12:00:00Z', is_read: false,
        is_flagged: false, has_attachments: false, snippet: 'Snippet',
        body: '', body_type: 'empty',
        parse_error: null, is_archived: false, attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-unarchived/sync-body' && init.method === 'POST') {
      return json({
        id: 'm-unarchived', account_id: 'acc-1', subject: 'Unarchived Email', from_address: 'u@x.test', from_name: 'Unarchived',
        from: 'Unarchived <u@x.test>', to: 'box@x.test', cc: '', date: '2018-10-26T12:00:00Z', is_read: false,
        is_flagged: false, has_attachments: false, snippet: 'Snippet',
        body: '<p>Instant fetched on-demand body</p>', body_type: 'html',
        parse_error: null, is_archived: true, attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-sync-failed') {
      return json({
        id: 'm-sync-failed', account_id: 'acc-1', subject: 'Sync Failed Email', from_address: 'f@x.test', from_name: 'Fail',
        from: 'Fail <f@x.test>', to: 'box@x.test', cc: '', date: '2018-10-26T12:00:00Z', is_read: false,
        is_flagged: false, has_attachments: false, snippet: null,
        body: '', body_type: 'empty',
        parse_error: null, is_archived: false, attachments: [],
      })
    }
    if (u === '/api/mail/messages/m-sync-failed/sync-body' && init.method === 'POST') {
      return json({ detail: 'Remote connection timeout' }, 500)
    }
    if (init.method === 'POST') {
      posts.push({ url: u, body: JSON.parse(String(init.body)) })
      return json({ id: 'm-1', account_id: 'acc-1', operation_id: 'op', is_flagged: true, success: true })
    }
    return json({ detail: 'unexpected' }, 404)
  }))
  queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item, nullDateItem, htmlItemWithImages, htmlItemOther, htmlItemLightRich, failedItem, failedItemWithSnippet, emptyNormalItem, unarchivedItem, syncFailedItem])
  useMailStore.setState({ selectedKey: 'm-1', theme: 'dark' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

describe('<MessageReader />', () => {
  it('keeps an unknown detail date blank instead of falling back to the selected row date', async () => {
    useMailStore.setState({ selectedKey: 'm-null-date' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      const senderHeader = container.querySelector('[data-ui="MR06"]')?.parentElement
      expect(senderHeader?.textContent).not.toContain('2026')
    })
  })

  it('renders only loading while detail is pending, even with an HTML preview', async () => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [{ ...item, body_preview: '<html>Hidden preview</html>' }])
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) =>
      String(url) === '/api/mail/messages/m-1'
        ? new Promise<Response>(() => {})
        : originalFetch(url, init),
    ))
    const { container } = await render(<MessageReader />)
    expect(container.textContent).toContain('正在加载正文…')
    expect(container.textContent).not.toContain('Hidden preview')
    expect(container.querySelector('[data-ui="MR07"]')).toBeNull()
    expect(container.querySelector('.reader-location')?.textContent).toBe('box@x.test')
    expect(container.querySelector('.email-body')).toBeNull()
    expect(container.querySelector('.empty-body-placeholder')).toBeNull()
  })

  it.each([true, false, null])('hides HTML previews for empty bodies (archived=%s)', async (archived) => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [{ ...unarchivedItem, body_preview: '<html><head><meta charset="utf-8"></head><body>Hidden preview</body></html>' }])
    useMailStore.setState({ selectedKey: 'm-unarchived' })
    const originalFetch = globalThis.fetch
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/sync-body')) return new Promise<Response>(() => {})
      const response = await originalFetch(url, init)
      if (String(url) !== '/api/mail/messages/m-unarchived') return response
      return json({ ...await response.json(), is_archived: archived })
    })
    vi.stubGlobal('fetch', fetchMock)
    const { container } = await render(<MessageReader />)
    await waitFor(() => {
      expect(container.querySelector('.empty-body-placeholder')).not.toBeNull()
      expect(container.textContent).toContain(archived === false ? '正在优先同步邮件正文…' : '邮件正文尚未完成同步或内容为空')
    })
    expect(container.textContent).not.toContain('Hidden preview')
    expect(container.querySelector('.email-body')).toBeNull()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sync-body'))).toHaveLength(archived === false ? 1 : 0)
  })

  it.each(['text', 'html'])('shows only the parse error with partial %s content', async (bodyType) => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const response = await originalFetch(url, init)
      if (String(url) !== '/api/mail/messages/m-1') return response
      return json({ ...await response.json(), body: '<p>Hidden partial content</p>', body_type: bodyType, parse_error: 'MIME parsing failed' })
    }))
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.textContent).toContain('MIME parsing failed'))
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
    expect(container.querySelector('.email-body')).toBeNull()
    expect(container.querySelector('.empty-body-placeholder')).toBeNull()
    expect(container.textContent).not.toContain('Hidden partial content')
  })

  it('shows only the request error when detail loading fails', async () => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) =>
      String(url) === '/api/mail/messages/m-1'
        ? Promise.resolve(json({ detail: 'Detail request failed' }, 500))
        : originalFetch(url, init),
    ))
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.textContent).toContain('Detail request failed'))
    expect(container.querySelector('[data-ui="MR07"]')).toBeNull()
    expect(container.querySelector('.reader-location')?.textContent).toBe('box@x.test')
    expect(container.querySelector('.email-body')).toBeNull()
    expect(container.querySelector('.empty-body-placeholder')).toBeNull()
  })

  it('renders the text body and attachment links by UUID with formatted size', async () => {
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.querySelector('.email-body-text')?.textContent).toBe('plain body text'))
    const link = container.querySelector('.attachment-list a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/api/mail/attachments/att-1')
    expect(link.getAttribute('download')).toBe('r.pdf')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.querySelector('small')?.textContent).toBe('10 B')
  })

  it('renders sender email address between MR06 and MR07', async () => {
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.querySelector('[data-ui="MR06"]')?.textContent).toBe('Ann'))
    expect(container.textContent).toContain('发件人：ann@x.test')
    await waitFor(() => expect(container.querySelector('[data-ui="MR07"]')?.textContent).toBe('收件人：box@x.test'))
  })

  it('renders only API-provided recipients and keeps account ownership separate', async () => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const response = await originalFetch(url, init)
      if (String(url) !== '/api/mail/messages/m-1') return response
      return json({ ...await response.json(), to: 'first@x.test, second@x.test' })
    }))
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      expect(container.querySelector('[data-ui="MR07"]')?.textContent).toBe('收件人：first@x.test, second@x.test')
    })
    expect(container.querySelector('.reader-location')?.textContent).toBe('box@x.test')
  })

  it.each([
    ['empty To with Bcc only', { to: '', bcc: 'blind-copy@x.test' }],
    ['missing To with Bcc only', { bcc: 'blind-copy@x.test' }],
  ])('does not infer a recipient from account or Bcc when To is %s', async (_label, recipientFields) => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const response = await originalFetch(url, init)
      if (String(url) !== '/api/mail/messages/m-1') return response
      const detail: Record<string, unknown> = { ...await response.json(), ...recipientFields }
      if (!Object.hasOwn(recipientFields, 'to')) delete detail.to
      return json(detail)
    }))
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      expect(container.querySelector('[data-ui="MR07"]')?.textContent).toBe('收件人：未提供')
    })
    expect(container.querySelector('.reader-location')?.textContent).toBe('box@x.test')
    expect(container.querySelector('[data-ui="MR07"]')?.textContent).not.toContain('box@x.test')
    expect(container.querySelector('[data-ui="MR07"]')?.textContent).not.toContain('blind-copy@x.test')
  })

  it('does not retain the previous message recipient after switching to a message without To', async () => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const response = await originalFetch(url, init)
      if (String(url) === '/api/mail/messages/m-1') {
        return json({ ...await response.json(), to: 'first@x.test' })
      }
      if (String(url) === '/api/mail/messages/m-2') {
        return json({ ...await response.json(), to: '', bcc: 'blind-copy@x.test' })
      }
      return response
    }))
    const { container } = await render(<MessageReader />)
    await waitFor(() => {
      expect(container.querySelector('[data-ui="MR07"]')?.textContent).toBe('收件人：first@x.test')
    })

    act(() => useMailStore.setState({ selectedKey: 'm-2' }))
    await waitFor(() => {
      expect(container.querySelector('[data-ui="MR07"]')?.textContent).toBe('收件人：未提供')
    })
    expect(container.querySelector('.reader-location')?.textContent).toBe('box@x.test')
    expect(container.querySelector('[data-ui="MR07"]')?.textContent).not.toContain('first@x.test')
  })

  it('does not render placeholder compose/reply/forward actions in reader toolbar', async () => {
    const { container } = await render(<MessageReader />)
    expect(container.querySelector('[aria-label=回复]')).toBeNull()
    expect(container.querySelector('[aria-label=回复所有人]')).toBeNull()
    expect(container.querySelector('[aria-label=转发]')).toBeNull()
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

  it('displays clear parse error banner with reason and hides empty placeholder on failed MIME (AC-006)', async () => {
    useMailStore.setState({ selectedKey: 'm-failed' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      expect(container.querySelector('[role="alert"]')).not.toBeNull()
      expect(container.textContent).toContain('邮件解析失败')
      expect(container.textContent).toContain('body_decode_failed: UnicodeDecodeError: invalid start byte')
    })
    // Must NOT mask failure with the empty body placeholder
    expect(container.textContent).not.toContain('邮件正文尚未完成同步或内容为空')
  })

  it('displays parse error even if snippet/preview exists and never masks failure (AC-006)', async () => {
    useMailStore.setState({ selectedKey: 'm-failed-snippet' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      expect(container.querySelector('[role="alert"]')).not.toBeNull()
      expect(container.textContent).toContain('邮件解析失败')
      expect(container.textContent).toContain('header_defect in From: UndecodableBytesDefect')
    })
    expect(container.textContent).not.toContain('邮件正文尚未完成同步或内容为空')
  })

  it('clears error when switching to normal email and restores error on switching back (AC-007)', async () => {
    // 1. Start on failed email
    useMailStore.setState({ selectedKey: 'm-failed' })
    const { container } = await render(<MessageReader />)
    await waitFor(() => expect(container.textContent).toContain('邮件解析失败'))

    // 2. Switch to normal email
    useMailStore.setState({ selectedKey: 'm-1' })
    await waitFor(() => expect(container.textContent).toContain('plain body text'))
    expect(container.textContent).not.toContain('邮件解析失败')
    expect(container.querySelector('[role="alert"]')).toBeNull()

    // 3. Switch back to failed email
    useMailStore.setState({ selectedKey: 'm-failed' })
    await waitFor(() => {
      expect(container.textContent).toContain('邮件解析失败')
      expect(container.querySelector('[role="alert"]')).not.toBeNull()
    })
  })

  it('displays empty body placeholder and not parse error for legitimate empty email (AC-007)', async () => {
    useMailStore.setState({ selectedKey: 'm-empty' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      expect(container.textContent).toContain('邮件正文尚未完成同步或内容为空')
    })
    expect(container.textContent).not.toContain('邮件解析失败')
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('displays syncing state on unarchived email and smoothly renders body after on-demand sync (AC-004)', async () => {
    useMailStore.setState({ selectedKey: 'm-unarchived' })
    const { container } = await render(<MessageReader />)

    // Trigger on-demand sync and verify body renders
    await waitFor(() => {
      const iframe = container.querySelector('iframe')
      expect(iframe).not.toBeNull()
      expect(iframe?.srcdoc).toContain('Instant fetched on-demand body')
    })
    expect(container.textContent).not.toContain('邮件解析失败')
  })

  it('displays error and retry button when on-demand sync fails (AC-005)', async () => {
    useMailStore.setState({ selectedKey: 'm-sync-failed' })
    const { container } = await render(<MessageReader />)

    await waitFor(() => {
      expect(container.textContent).toContain('Remote connection timeout')
      expect(container.textContent).toContain('立即重试同步')
    })
  })

  it('does not crash and renders cleanly when non-mail queries are present in QueryCache (AC-001, AC-002)', async () => {
    queryClient.setQueryData(['mail-core', 'account-folders', 'acc-1'], [
      { folder_id: 'folder-junk', name: '垃圾邮件', role: 'junk', unread_count: 2, total_count: 2 },
    ])
    queryClient.setQueryData(queryKeys.inbox('acc-1'), [
      {
        id: 'msg-catie',
        subject: 'Public benchmarks',
        from: 'catie@example.com',
        is_read: false,
        is_flagged: false,
        has_attachments: false,
        accountId: 'acc-1',
        accountEmail: 'a@x.test',
      },
    ])
    useMailStore.setState({ selectedKey: 'msg-catie' })
    const { container } = await render(<MessageReader />)
    await waitFor(() => {
      expect(container.textContent).toContain('Public benchmarks')
    })
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })
})
