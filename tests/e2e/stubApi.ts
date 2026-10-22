import type { Page, Route } from '@playwright/test'

export interface MockMessage {
  id: string
  subject: string
  from: string
  to?: string
  date: string
  is_read: boolean
  is_flagged: boolean
  has_attachments: boolean
  body_preview: string
  body_html: string
  accountEmail: string
  accountId: string
}

export function createMockMessages(): MockMessage[] {
  return [
    {
      id: 'msg-00000000-0000-0000-0000-000000000001',
      subject: '欢迎体验 kkmail 邮件内核',
      from: 'team@kkmail.local',
      to: 'user@example.com',
      date: '2026-10-21T08:00:00Z',
      is_read: false,
      is_flagged: false,
      has_attachments: false,
      body_preview: '欢迎使用现代高性能多账户邮件系统。',
      body_html: '<h1>欢迎使用 kkmail</h1><p>这是一封测试邮件，体验本地优先与端到端响应。</p>',
      accountEmail: 'user@example.com',
      accountId: 'acc-00000000-0000-0000-0000-000000000001',
    },
    {
      id: 'msg-00000000-0000-0000-0000-000000000002',
      subject: '关于安全与加密凭据的重要说明',
      from: 'security@kkmail.local',
      to: 'user@example.com',
      date: '2026-10-20T12:00:00Z',
      is_read: true,
      is_flagged: true,
      has_attachments: true,
      body_preview: '系统采用 AES-GCM 存储 Blob，凭据通过密钥环加密保护。',
      body_html: '<p>系统采用 <strong>AES-GCM</strong> 存储 Blob，所有凭据加密存储。</p>',
      accountEmail: 'user@example.com',
      accountId: 'acc-00000000-0000-0000-0000-000000000001',
    },
    {
      id: 'msg-00000000-0000-0000-0000-000000000003',
      subject: '季度运营汇总报告',
      from: 'analytics@kkmail.local',
      to: 'user@example.com',
      date: '2026-10-19T10:00:00Z',
      is_read: true,
      is_flagged: false,
      has_attachments: false,
      body_preview: '收件箱增量同步完成，数据库索引性能平稳。',
      body_html: '<p>季度报告数据汇总完毕，全文检索与 Keyset 游标均已就绪。</p>',
      accountEmail: 'user@example.com',
      accountId: 'acc-00000000-0000-0000-0000-000000000001',
    },
  ]
}

export const FAKE_CSRF_TOKEN = 'fake-csrf-token'

export async function setupStubApi(page: Page, options: { authedInitially?: boolean } = {}) {
  let isAuthed = options.authedInitially ?? false
  const messages = createMockMessages()

  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method().toUpperCase()

    // 1. Auth check
    if (path === '/api/auth/me') {
      if (!isAuthed) {
        return route.fulfill({ status: 401, json: { detail: '未登录' } })
      }
      return route.fulfill({
        status: 200,
        json: { username: 'kkmail', email: 'user@example.com', csrf_token: FAKE_CSRF_TOKEN, via: 'session' },
      })
    }

    // 2. Login
    if (path === '/api/auth/login' && method === 'POST') {
      const postData = req.postDataJSON() || {}
      if (postData.password === 'correct-password') {
        isAuthed = true
        return route.fulfill({
          status: 200,
          headers: {
            'Set-Cookie': 'kkmail_session=fake-session-cookie; Path=/; HttpOnly',
            'X-CSRF-Token': FAKE_CSRF_TOKEN,
          },
          json: { ok: true, username: 'kkmail', csrf_token: FAKE_CSRF_TOKEN },
        })
      }
      return route.fulfill({ status: 401, json: { detail: '登录密码错误' } })
    }

    // If not authed, reject unsafe endpoints
    if (!isAuthed) {
      return route.fulfill({ status: 401, json: { detail: '未登录' } })
    }

    // Enforce CSRF on all state-mutating requests
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const csrfHeader = req.headers()['x-csrf-token']
      if (csrfHeader !== FAKE_CSRF_TOKEN) {
        return route.fulfill({
          status: 403,
          json: { detail: { error: 'CSRF validation failed', csrf_error: true } },
        })
      }
    }

    // 2.1 Logout
    if (path === '/api/auth/logout' && method === 'POST') {
      isAuthed = false
      return route.fulfill({
        status: 200,
        headers: {
          'Set-Cookie': 'kkmail_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT',
        },
        json: { ok: true },
      })
    }

    // 3. Groups & Accounts & Settings
    if (path === '/api/groups') {
      return route.fulfill({
        status: 200,
        json: { groups: [{ id: 'grp-1', name: '工作邮箱', color: '#0879d9', account_count: 1 }] },
      })
    }

    if (path === '/api/accounts') {
      return route.fulfill({
        status: 200,
        json: {
          accounts: [
            {
              id: 'acc-00000000-0000-0000-0000-000000000001',
              email: 'user@example.com',
              provider: 'imap',
              group_id: 'grp-1',
              sync_state: 'idle',
              sync_enabled: true,
            },
          ],
          total: 1,
          has_more: false,
        },
      })
    }

    if (path === '/api/settings') {
      return route.fulfill({
        status: 200,
        json: { theme: 'dark', poll_interval_s: 60 },
      })
    }

    // 4. Folder stats
    if (path.includes('/folder-stats') || path.includes('/stats')) {
      return route.fulfill({
        status: 200,
        json: {
          account_id: 'acc-00000000-0000-0000-0000-000000000001',
          folders: [
            { folder_id: 'f-inbox', role: 'inbox', name: '收件箱', total_count: messages.length, unread_count: 1 },
          ],
        },
      })
    }

    // 5. Mail Inbox
    if (path === '/api/mail/inbox') {
      const sortOrder = url.searchParams.get('sort_order') || 'desc'
      const sorted = [...messages].sort((a, b) => {
        const diff = new Date(a.date).getTime() - new Date(b.date).getTime()
        return sortOrder === 'asc' ? diff : -diff
      })
      const items = sorted.map((m) => ({
        id: m.id,
        subject: m.subject,
        from_address: m.from,
        from_name: m.from.split('@')[0],
        sort_time: m.date,
        is_read: m.is_read,
        is_flagged: m.is_flagged,
        has_attachments: m.has_attachments,
        snippet: m.body_preview,
        folder_id: 'f-inbox',
        account_id: m.accountId,
      }))
      return route.fulfill({
        status: 200,
        json: { items, next_cursor: null },
      })
    }

    // 6. Search
    if (path === '/api/mail/search') {
      const q = url.searchParams.get('q') || ''
      const filtered = messages.filter((m) => m.subject.includes(q) || m.body_preview.includes(q))
      const items = filtered.map((m) => ({
        id: m.id,
        subject: m.subject,
        from_address: m.from,
        from_name: m.from.split('@')[0],
        sort_time: m.date,
        is_read: m.is_read,
        is_flagged: m.is_flagged,
        has_attachments: m.has_attachments,
        snippet: m.body_preview,
        folder_id: 'f-inbox',
        account_id: m.accountId,
      }))
      return route.fulfill({
        status: 200,
        json: { query: q, items, total: filtered.length, offset: 0, next_offset: null },
      })
    }

    // 7. Message detail
    const detailMatch = path.match(/^\/api\/mail\/messages\/([^/]+)$/)
    if (detailMatch && method === 'GET') {
      const id = detailMatch[1]
      const hit = messages.find((m) => m.id === id)
      if (!hit) {
        return route.fulfill({ status: 404, json: { detail: '邮件未找到' } })
      }
      return route.fulfill({
        status: 200,
        json: {
          id: hit.id,
          subject: hit.subject,
          from_address: hit.from,
          from_name: hit.from.split('@')[0],
          to_addresses: [{ address: hit.to || 'user@example.com' }],
          cc_addresses: [],
          sort_time: hit.date,
          is_read: hit.is_read,
          is_flagged: hit.is_flagged,
          has_attachments: hit.has_attachments,
          body_text: hit.body_preview,
          body_html: hit.body_html,
          body_type: 'html',
          attachments: hit.has_attachments
            ? [{ id: 'att-1', name: 'security_audit.pdf', size: 102400, contentType: 'application/pdf' }]
            : [],
        },
      })
    }

    // 8. Mutations (read / flag / trash / mark-all-read)
    if (path === '/api/mail/mark-all-read' && method === 'POST') {
      let count = 0
      for (const m of messages) {
        if (!m.is_read) {
          m.is_read = true
          count++
        }
      }
      return route.fulfill({ status: 200, json: { success: true, count } })
    }
    const readMatch = path.match(/^\/api\/mail\/messages\/([^/]+)\/read$/)
    if (readMatch && method === 'POST') {
      const mid = readMatch[1]
      const target = messages.find((m) => m.id === mid)
      if (target) {
        const body = req.postDataJSON() || {}
        target.is_read = body.is_read ?? true
      }
      return route.fulfill({ status: 200, json: { ok: true } })
    }
    if (path.includes('/flag') && method === 'POST') {
      return route.fulfill({ status: 200, json: { ok: true } })
    }
    if (path.includes('/trash') && method === 'POST') {
      return route.fulfill({ status: 200, json: { ok: true } })
    }

    // 9. Realtime SSE
    if (path === '/api/events') {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: ': keepalive\n\n',
      })
    }

    return route.fulfill({ status: 404, json: { detail: `Unknown stub path ${path}` } })
  })
}
