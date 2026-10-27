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
  parse_error?: string | null
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
    {
      id: 'msg-00000000-0000-0000-0000-000000000004',
      subject: '解析失败的损坏测试邮件',
      from: 'corrupt@kkmail.local',
      to: 'user@example.com',
      date: '2026-10-18T10:00:00Z',
      is_read: true,
      is_flagged: false,
      has_attachments: false,
      body_preview: '部分头部摘要',
      body_html: '',
      parse_error: 'body_decode_failed: UnicodeDecodeError: invalid start byte',
      accountEmail: 'user@example.com',
      accountId: 'acc-00000000-0000-0000-0000-000000000001',
    },
  ]
}

export interface StubFolder {
  folder_id: string
  role?: string
  name: string
  total_count?: number
  unread_count?: number
  remote_id?: string
  parent_remote_id?: string | null
}

export interface StubAccount {
  id: string
  email: string
  provider?: string
  account_type?: string
  group_id?: string
  group_color?: string
  master_order?: number | null
  group_order?: number | null
  sync_state?: string
  sync_enabled?: boolean
}

export interface StubGroup {
  id: string
  name: string
  color?: string | null
  sort_order?: number
}

export interface SetupStubApiOptions {
  authedInitially?: boolean
  accounts?: StubAccount[]
  groups?: StubGroup[]
  folderStatsByAccount?: Record<string, StubFolder[] | { error: string }>
}

export const FAKE_CSRF_TOKEN = 'fake-csrf-token'

export async function setupStubApi(page: Page, options: SetupStubApiOptions = {}) {
  let isAuthed = options.authedInitially ?? false
  const messages = createMockMessages()
  let currentGroups = options.groups ?? [{ id: 'grp-1', name: '测试邮箱组', color: '#0879d9', sort_order: 0 }]
  let currentAccounts = options.accounts ?? [
    {
      id: 'acc-00000000-0000-0000-0000-000000000001',
      email: 'user@example.com',
      provider: 'imap',
      group_id: 'grp-1',
      sync_state: 'idle',
      sync_enabled: true,
    },
  ]
  let oauthDraft: Record<string, unknown> | null = null
  let sidebarRevision = 0

  const getSidebarLayout = () => {
    const groupIds = [...currentGroups]
      .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name, 'en', { sensitivity: 'base' }))
      .map((group) => group.id)
    const groupAccountIds = Object.fromEntries(currentGroups.map((group) => {
      const members = currentAccounts.filter((account) => account.group_id === group.id)
      const hasManualOrder = members.some((account) => account.group_order != null)
      members.sort((a, b) => hasManualOrder
        ? (a.group_order ?? Number.MAX_SAFE_INTEGER) - (b.group_order ?? Number.MAX_SAFE_INTEGER) || a.email.localeCompare(b.email, 'en', { sensitivity: 'base' })
        : a.email.localeCompare(b.email, 'en', { sensitivity: 'base' }))
      return [group.id, members.map((account) => account.id)]
    }))
    return {
      revision: String(sidebarRevision).padStart(64, '0'),
      group_ids: groupIds,
      master_account_ids: currentAccounts.map((account) => account.id),
      ungrouped_account_ids: currentAccounts.filter((account) => !account.group_id).map((account) => account.id),
      group_account_ids: groupAccountIds,
    }
  }

  const syncReport = (id: string, targetCount: number, state: string) => ({
    id,
    mode: 'delta',
    trigger: 'manual',
    state,
    target_count: targetCount,
    queued_count: 0,
    running_count: state === 'complete' ? 0 : targetCount,
    completed_count: state === 'complete' ? targetCount : 0,
    failed_count: 0,
    created_at: '2026-10-28T00:00:00Z',
    finished_at: state === 'complete' ? '2026-10-28T00:00:05Z' : null,
    errors: [] as unknown[],
  })

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
        json: { groups: currentGroups.map((group, sort_order) => ({
          ...group,
          sort_order: group.sort_order ?? sort_order,
          account_count: currentAccounts.filter((account) => account.group_id === group.id).length,
        })) },
      })
    }

    if (path === '/api/accounts' && method === 'GET') {
      const accountsList = currentAccounts
      const limit = Math.max(1, Number(url.searchParams.get('limit') || 200))
      const offset = Math.max(0, Number(url.searchParams.get('offset') || 0))
      return route.fulfill({
        status: 200,
        json: {
          accounts: accountsList.slice(offset, offset + limit),
          total: accountsList.length,
          limit,
          offset,
          has_more: offset + limit < accountsList.length,
        },
      })
    }

    if (path === '/api/accounts' && method === 'POST') {
      const body = (req.postDataJSON() || {}) as Record<string, unknown>
      const newAcc: StubAccount = {
        id: `acc-${currentAccounts.length + 1}`,
        email: String(body.email || 'oauth-new@outlook.com'),
        provider: String(body.provider || 'graph'),
        account_type: String(body.provider || 'graph'),
        group_id: body.group_id ? String(body.group_id) : undefined,
        sync_state: 'idle',
        sync_enabled: true,
      }
      currentAccounts = [...currentAccounts, newAcc]
      oauthDraft = null
      return route.fulfill({ status: 200, json: { ...newAcc, status: 'active', sync_status: 'idle' } })
    }

    // Manual immediate sync: the POSTs accept a sync request and the report
    // endpoint immediately shows it complete, so the UI's wait-for-sync flow
    // (spin until the request finishes) settles without extra stub state.
    if (path === '/api/accounts/sync-all' && method === 'POST') {
      return route.fulfill({ status: 202, json: syncReport('stub-sync-all', currentAccounts.length, 'complete') })
    }

    const accountSyncMatch = path.match(/^\/api\/accounts\/([^/]+)\/sync$/)
    if (accountSyncMatch && method === 'POST') {
      return route.fulfill({ status: 202, json: syncReport(`stub-sync-${decodeURIComponent(accountSyncMatch[1])}`, 1, 'complete') })
    }

    const syncRequestMatch = path.match(/^\/api\/mail\/sync\/requests\/([^/]+)$/)
    if (syncRequestMatch && method === 'GET') {
      return route.fulfill({ status: 200, json: syncReport(decodeURIComponent(syncRequestMatch[1]), 1, 'complete') })
    }

    const patchAccountMatch = path.match(/^\/api\/accounts\/([^/]+)$/)
    if (patchAccountMatch && method === 'PATCH') {
      const id = decodeURIComponent(patchAccountMatch[1])
      const found = currentAccounts.find(a => a.id === id) || currentAccounts[0]
      const body = req.postDataJSON() || {}
      if (body.oauth_flow_id) oauthDraft = null
      currentAccounts = currentAccounts.map(a => a.id === id ? { ...a, sync_state: 'idle' } : a)
      return route.fulfill({ status: 200, json: { ...found, status: 'active', sync_status: 'idle' } })
    }

    if (path === '/api/accounts/oauth/metadata' && method === 'GET') {
      const provider = url.searchParams.get('provider') || 'microsoft'
      return route.fulfill({
        status: 200,
        json: {
          provider,
          runtime_mode: 'desktop',
          default_client_type: 'public',
          redirect_uri: `http://127.0.0.1:18765/api/accounts/oauth/callback/${provider}`,
          callback_path: `/api/accounts/oauth/callback/${provider}`,
          origin_configured: true,
          notice: null,
        },
      })
    }

    if (path === '/api/accounts/oauth/active' && method === 'GET') {
      return route.fulfill({ status: 200, json: { flow: oauthDraft } })
    }

    if (path === '/api/accounts/oauth/start' && method === 'POST') {
      const body = (req.postDataJSON() || {}) as Record<string, unknown>
      const provider = String(body.provider || 'microsoft')
      const intent = String(body.intent || 'create')
      oauthDraft = {
        flow_id: 'stub-oauth-flow-1', provider, intent, account_id: body.account_id || null,
        group_id: body.group_id || null, client_type: body.client_type || 'public',
        client_id: body.client_id || 'stub-client-id', status: 'authorized',
        verified_email: intent === 'reauthorize' ? currentAccounts.find(a => a.id === body.account_id)?.email : 'oauth-new@outlook.com',
        method: body.method || 'authorization_code', tenant: body.tenant || null,
        user_code: body.method === 'device_code' ? 'ABCD-EFGH' : null,
        verification_uri: body.method === 'device_code' ? 'https://microsoft.com/devicelogin' : null,
        error: null, redirect_uri: `http://127.0.0.1:18765/api/accounts/oauth/callback/${provider}`,
        expires_at: 9999999999,
      }
      return route.fulfill({
        status: 200,
        json: {
          flow_id: 'stub-oauth-flow-1',
          provider,
          intent,
          status: 'pending',
          auth_url: `http://127.0.0.1:18765/api/accounts/oauth/callback/${provider}?state=stub-state&code=stub-code`,
          redirect_uri: `http://127.0.0.1:18765/api/accounts/oauth/callback/${provider}`,
          client_type: String(body.client_type || 'public'),
          expires_at: 9999999999,
          method: body.method || 'authorization_code', tenant: body.tenant || null,
          user_code: body.method === 'device_code' ? 'ABCD-EFGH' : null,
          verification_uri: body.method === 'device_code' ? 'https://microsoft.com/devicelogin' : null,
        },
      })
    }

    if (path.endsWith('/poll') && path.startsWith('/api/accounts/oauth/flows/')) {
      return route.fulfill({ status: 200, json: oauthDraft })
    }

    if (path === '/api/accounts/oauth/flows/stub-oauth-flow-1' && method === 'GET') {
      return route.fulfill({
        status: 200,
        json: oauthDraft,
      })
    }

    if (path.endsWith('/cancel') && path.startsWith('/api/accounts/oauth/flows/')) {
      oauthDraft = null
      return route.fulfill({ status: 200, json: { ok: true, status: 'cancelled' } })
    }

    if (path === '/api/sidebar/layout' && method === 'GET') {
      return route.fulfill({ status: 200, json: getSidebarLayout() })
    }

    if (path === '/api/settings') {
      return route.fulfill({
        status: 200,
        json: { theme: 'dark', poll_interval_s: 60 },
      })
    }

    if (path === '/api/sidebar/layout' && method === 'PUT') {
      const layout = req.postDataJSON() as {
        expected_revision: string
        group_ids: string[]
        master_account_ids: string[]
        ungrouped_account_ids: string[]
        group_account_ids: Record<string, string[]>
      }
      if (layout.expected_revision !== String(sidebarRevision).padStart(64, '0')) {
        return route.fulfill({ status: 409, json: { detail: 'sidebar layout changed; reload and retry' } })
      }
      currentGroups = layout.group_ids.map((id, sort_order) => {
        const group = currentGroups.find((item) => item.id === id)
        return group ? { ...group, sort_order } : null
      }).filter((group): group is StubGroup => group !== null)
      currentAccounts = currentAccounts.map((account) => {
        const group = currentGroups.find((item) => layout.group_account_ids[item.id]?.includes(account.id))
        const groupOrder = group ? layout.group_account_ids[group.id].indexOf(account.id) : null
        return {
          ...account,
          group_id: group?.id,
          master_order: layout.master_account_ids.indexOf(account.id),
          group_order: groupOrder,
        }
      }).sort((a, b) => (a.master_order ?? Number.MAX_SAFE_INTEGER) - (b.master_order ?? Number.MAX_SAFE_INTEGER))
      sidebarRevision += 1
      return route.fulfill({ status: 204, body: '' })
    }

    if (path === '/api/sidebar/layout/default-order' && method === 'POST') {
      const body = req.postDataJSON() as { expected_revision: string }
      if (body.expected_revision !== String(sidebarRevision).padStart(64, '0')) {
        return route.fulfill({ status: 409, json: { detail: 'sidebar layout changed; reload and retry' } })
      }
      currentAccounts = currentAccounts.map((account) => ({ ...account, master_order: null, group_order: null }))
        .sort((a, b) => a.email.localeCompare(b.email, 'en', { sensitivity: 'base' }))
      sidebarRevision += 1
      return route.fulfill({ status: 204, body: '' })
    }

    // 4. Global Stats & Folder stats
    if (path === '/api/mail/stats') {
      return route.fulfill({
        status: 200,
        json: {
          total_unread: 1,
          accounts: currentAccounts.map((a) => ({
            account_id: a.id,
            unread_count: 1,
            total_count: messages.length,
          })),
        },
      })
    }

    const folderStatsMatch = path.match(/^\/api\/mail\/accounts\/([^/]+)\/folder-stats$/)
    if (folderStatsMatch) {
      const accountId = decodeURIComponent(folderStatsMatch[1])
      if (options.folderStatsByAccount && options.folderStatsByAccount[accountId]) {
        const val = options.folderStatsByAccount[accountId]
        if ('error' in val) {
          return route.fulfill({ status: 500, json: { detail: val.error } })
        }
        return route.fulfill({
          status: 200,
          json: {
            account_id: accountId,
            folders: val,
          },
        })
      }
      return route.fulfill({
        status: 200,
        json: {
          account_id: accountId,
          folders: [
            { folder_id: 'f-inbox', role: 'inbox', name: '收件箱', total_count: messages.length, unread_count: 1 },
          ],
        },
      })
    }

    if (path.includes('/folder-stats')) {
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
        account_email: currentAccounts.find((account) => account.id === m.accountId)?.email ?? null,
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
        account_email: currentAccounts.find((account) => account.id === m.accountId)?.email ?? null,
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
          parse_error: hit.parse_error ?? null,
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

    // 8.5 Activity heartbeat (registered explicitly so these
    // POSTs never fall into the 404 string-detail fallback)
    if (path === '/api/mail/sync/activity' && method === 'POST') {
      return route.fulfill({ status: 204, body: '' })
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
