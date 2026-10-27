// @vitest-environment jsdom
import { createElement, useEffect } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { heartbeatAccountIds, newClientRequestId, useScopeSync } from './use_scope_sync'
import { queryClient, queryKeys } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { cleanup, render, waitFor } from '../test/render'
import { clearDiagnosticLogs, getDiagnosticLogs } from '../lib/diagnostics'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function completeDelta(id = 'req-1') {
  return json({
    id, mode: 'delta', trigger: 'manual', state: 'complete', target_count: 1,
    queued_count: 0, running_count: 0, completed_count: 1, failed_count: 0,
    created_at: '2026-10-26T00:00:00Z', errors: [],
  }, 202)
}

interface FetchCall { url: string; method: string; headers: Headers; body: unknown }
let calls: FetchCall[] = []
let hookApi: ReturnType<typeof useScopeSync> | null = null

function Harness() {
  const api = useScopeSync(true)
  useEffect(() => { hookApi = api })
  return null
}

function deltaCalls() {
  return calls.filter((c) => c.url.endsWith('/api/mail/sync/delta'))
}
function activityCalls() {
  return calls.filter((c) => c.url.endsWith('/api/mail/sync/activity'))
}

beforeEach(() => {
  calls = []
  hookApi = null
  clearDiagnosticLogs()
})

afterEach(() => {
  cleanup()
  clearDiagnosticLogs()
})

describe('useScopeSync (p053/R01)', () => {
  it('sends delta sync through the unified client with the CSRF header', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))

    // The navigation auto-trigger fires on mount via the unified client.
    await waitFor(() => expect(deltaCalls()).toHaveLength(1))
    expect(deltaCalls()[0].headers.get('X-CSRF-Token')).toBe('tok-abc')
    expect(deltaCalls()[0].body).toMatchObject({ folder_role: 'inbox', trigger: 'navigation' })
    await waitFor(() => expect(hookApi?.isSyncing).toBe(false))
    expect(hookApi?.lastError).toBeNull()
  })

  it('renders an object-shaped error detail readably, never "[object Object]"', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) {
        return json({ detail: [{ loc: ['body', 'folder_role'], msg: 'folder_role 不合法', type: 'value_error' }] }, 422)
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))

    await waitFor(() => expect(hookApi?.lastError).toBe('folder_role 不合法'))
    expect(hookApi?.lastError).not.toContain('[object Object]')
    expect(hookApi?.isSyncing).toBe(false)
  })

  it('heartbeat posts activity via the unified client only while visible, and failures go to diagnostics not the banner', async () => {
    vi.useFakeTimers()
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-1', email: 'a@x.test' } })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      if (u.endsWith('/api/mail/sync/activity')) return json({ detail: 'heartbeat boom' }, 500)
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(activityCalls()).toHaveLength(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(activityCalls()).toHaveLength(1)
    expect(activityCalls()[0].headers.get('X-CSRF-Token')).toBe('tok-abc')
    expect(activityCalls()[0].body).toEqual({ account_ids: ['acc-1'] })

    // The failed heartbeat must not become a repeating user-facing error…
    expect(hookApi?.lastError).toBeNull()
    // …but must land in the sanitized diagnostics channel.
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(getDiagnosticLogs().some((entry) => entry.message === '活动心跳上报失败')).toBe(true)

    // Hidden page: no further heartbeats.
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    await act(async () => { await vi.advanceTimersByTimeAsync(40_000) })
    expect(activityCalls()).toHaveLength(1)
    vi.useRealTimers()
  })

  it('auto-trigger cooldown is per scope: switching folders within 12s still syncs the new folder (F2)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      return json({ detail: 'unexpected' }, 404)
    }))
    let now = 1_000_000
    const dateSpy = vi.spyOn(Date, 'now').mockImplementation(() => now)
    try {
      useMailStore.setState({
        view: { type: 'folder', accountId: 'acc-1', email: 'a@x.test', folderId: 'f-inbox', folderName: '收件箱', folderRole: 'inbox' },
      })
      await render(createElement(Harness))
      await waitFor(() => expect(deltaCalls()).toHaveLength(1))
      expect(deltaCalls()[0].body).toMatchObject({ folder_id: 'f-inbox', trigger: 'navigation' })

      // Five seconds later — inside the old shared 12s cooldown — open a
      // different folder: its navigation sync must still fire.
      now += 5_000
      act(() => {
        useMailStore.setState({
          view: { type: 'folder', accountId: 'acc-1', email: 'a@x.test', folderId: 'f-sent', folderName: '已发送', folderRole: 'sent' },
        })
      })
      await waitFor(() => expect(deltaCalls()).toHaveLength(2))
      expect(deltaCalls()[1].body).toMatchObject({ folder_id: 'f-sent', trigger: 'navigation' })

      // Switching straight back is still within the first folder's own
      // cooldown, so no third trigger fires.
      act(() => {
        useMailStore.setState({
          view: { type: 'folder', accountId: 'acc-1', email: 'a@x.test', folderId: 'f-inbox', folderName: '收件箱', folderRole: 'inbox' },
        })
      })
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(deltaCalls()).toHaveLength(2)
    } finally {
      dateSpy.mockRestore()
    }
  })
})

describe('newClientRequestId (A336)', () => {
  it('generates RFC 4122 UUID-shaped idempotency keys that do not repeat', () => {
    const ids = new Set(Array.from({ length: 200 }, () => newClientRequestId()))
    expect(ids.size).toBe(200)
    for (const id of ids) {
      expect(id).toMatch(/^req_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
    }
  })

  it('sends the UUID-shaped key as client_request_id on the delta POST', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))
    await waitFor(() => expect(deltaCalls()).toHaveLength(1))
    const body = deltaCalls()[0].body as { client_request_id?: string }
    expect(body.client_request_id).toMatch(/^req_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
  })
})

describe('heartbeat account set (A362)', () => {
  const accounts = [
    { id: 'acc-1', group_id: 'g-1', sync_enabled: true },
    { id: 'acc-2', group_id: 'g-1', sync_enabled: false },
    { id: 'acc-3', group_id: null, sync_enabled: true },
  ]

  it('resolves the account set per scope from the accounts cache', () => {
    expect(heartbeatAccountIds({ account_id: 'acc-9' }, accounts)).toEqual(['acc-9'])
    expect(heartbeatAccountIds({}, accounts)).toEqual(['acc-1', 'acc-3'])
    expect(heartbeatAccountIds({ group_id: 'g-1' }, accounts)).toEqual(['acc-1'])
    expect(heartbeatAccountIds({}, undefined)).toEqual([])
    expect(heartbeatAccountIds({ group_id: 'g-x' }, accounts)).toEqual([])
  })

  function stubHeartbeatFetch() {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      if (u.endsWith('/api/mail/sync/activity')) return new Response(null, { status: 204 })
      return json({ detail: 'unexpected' }, 404)
    }))
  }

  it('global view heartbeat reports every enabled account instead of never sending', async () => {
    vi.useFakeTimers()
    useMailStore.setState({ view: { type: 'allInbox' } })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    queryClient.setQueryData(queryKeys.accounts, accounts)
    stubHeartbeatFetch()

    await render(createElement(Harness))
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(activityCalls()).toHaveLength(1)
    expect(activityCalls()[0].body).toEqual({ account_ids: ['acc-1', 'acc-3'] })
    vi.useRealTimers()
  })

  it('group view heartbeat reports the group\u2019s enabled accounts', async () => {
    vi.useFakeTimers()
    useMailStore.setState({ view: { type: 'group', groupId: 'g-1', groupName: 'G', category: 'inbox' } })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    queryClient.setQueryData(queryKeys.accounts, accounts)
    stubHeartbeatFetch()

    await render(createElement(Harness))
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(activityCalls()).toHaveLength(1)
    expect(activityCalls()[0].body).toEqual({ account_ids: ['acc-1'] })
    vi.useRealTimers()
  })
})

describe('useScopeSync authoritative progress (R07)', () => {
  interface ServerReq {
    id: string
    state: string
    errors?: Array<{ code: string; safe_message: string | null }>
  }

  let server: Map<string, ServerReq>
  let listResult: ServerReq[]
  let postCount: number
  let getCounts: Map<string, number>
  let failGets: boolean

  function reqBody(r: ServerReq) {
    return {
      id: r.id, mode: 'delta', trigger: 'manual', state: r.state, target_count: 1,
      queued_count: r.state === 'queued' ? 1 : 0,
      running_count: r.state === 'running' ? 1 : 0,
      completed_count: r.state === 'complete' ? 1 : 0,
      failed_count: r.state === 'failed' ? 1 : 0,
      created_at: '2026-10-26T00:00:00Z', finished_at: null, errors: r.errors ?? [],
    }
  }

  function setVisibility(value: 'visible' | 'hidden') {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value })
  }

  // TanStack Query's notifyManager schedules subscriber notifications with
  // the real setTimeout(0) captured at module load, so under fake timers a
  // flush must also pump a few real macrotasks for query results to reach
  // the component.
  const realSetTimeout = globalThis.setTimeout
  async function flush(ms = 0) {
    // Query notifications and React's render scheduling cross the fake/real
    // timer boundary (and a ~1ms observer stale timer) more than once before
    // hook state settles, so pump real macrotasks interleaved with small
    // fake-time advances.
    await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
    for (let i = 0; i < 6; i += 1) {
      await act(async () => { await new Promise((r) => realSetTimeout(r, 2)) })
      await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    }
  }

  function getCount(id: string) {
    return getCounts.get(id) ?? 0
  }

  function listCalls() {
    return calls.filter((c) => c.url.startsWith('/api/mail/sync/requests?'))
  }

  beforeEach(() => {
    vi.useFakeTimers()
    server = new Map()
    listResult = []
    postCount = 0
    getCounts = new Map()
    failGets = false
    setVisibility('visible')
    useMailStore.setState({ view: { type: 'allInbox' } })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) {
        postCount += 1
        const req: ServerReq = { id: `srv-${postCount}`, state: 'queued' }
        server.set(req.id, req)
        return json(reqBody(req), 202)
      }
      const single = u.match(/\/api\/mail\/sync\/requests\/([^/?]+)$/)
      if (single) {
        const id = decodeURIComponent(single[1])
        getCounts.set(id, getCount(id) + 1)
        if (failGets) throw new TypeError('network down')
        const req = server.get(id)
        if (!req) return json({ detail: 'not found' }, 404)
        return json(reqBody(req))
      }
      if (u.startsWith('/api/mail/sync/requests?')) return json(listResult.map(reqBody))
      if (u.endsWith('/api/mail/sync/activity')) return new Response(null, { status: 204 })
      return json({ detail: 'unexpected' }, 404)
    }))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    setVisibility('visible')
  })

  it('queued -> polls -> terminal success clears isSyncing and stops polling', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)

    // Navigation auto-trigger POSTed once; the request is queued (202).
    expect(postCount).toBe(1)
    expect(hookApi?.isSyncing).toBe(true)
    const id = [...server.keys()][0]

    await flush(2_000)
    expect(getCount(id)).toBeGreaterThanOrEqual(1)
    expect(hookApi?.isSyncing).toBe(true)

    server.get(id)!.state = 'complete'
    await flush(2_000)
    expect(hookApi?.isSyncing).toBe(false)
    expect(hookApi?.lastError).toBeNull()

    const settledCount = getCount(id)
    await flush(10_000)
    expect(getCount(id)).toBe(settledCount)
  })

  it('terminal failure stops the spinner with a readable error', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    const id = [...server.keys()][0]
    expect(hookApi?.isSyncing).toBe(true)

    const req = server.get(id)!
    req.state = 'failed'
    req.errors = [{ code: 'provider_auth', safe_message: '邮箱登录失败，请检查凭据' }]
    await flush(2_000)

    expect(hookApi?.isSyncing).toBe(false)
    expect(hookApi?.lastError).toBe('邮箱登录失败，请检查凭据')
    expect(hookApi?.lastError).not.toContain('[object Object]')

    const settledCount = getCount(id)
    await flush(6_000)
    expect(getCount(id)).toBe(settledCount)
  })

  it('completes via polling alone in a no-SSE environment', async () => {
    // This harness never mounts the realtime/SSE hook; polling is the only
    // channel that can deliver the terminal state.
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    const id = [...server.keys()][0]
    expect(hookApi?.isSyncing).toBe(true)

    server.get(id)!.state = 'complete'
    await flush(2_000)
    expect(hookApi?.isSyncing).toBe(false)
    expect(getCount(id)).toBeGreaterThanOrEqual(1)
  })

  it('a polling network error means progress unavailable, never a fabricated terminal state', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    const id = [...server.keys()][0]
    expect(hookApi?.isSyncing).toBe(true)

    failGets = true
    await flush(2_000)
    // Still spinning on the last known non-terminal state; no fake success,
    // no fake failure surfaced as the sync error.
    expect(hookApi?.isSyncing).toBe(true)
    expect(hookApi?.progressUnavailable).toBe(true)
    expect(hookApi?.lastError).toBeNull()

    failGets = false
    server.get(id)!.state = 'complete'
    await flush(2_000)
    expect(hookApi?.progressUnavailable).toBe(false)
    expect(hookApi?.isSyncing).toBe(false)
  })

  it('blocks duplicate manual submission for the same scope while a request is in flight', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    expect(postCount).toBe(1)
    expect(hookApi?.isSyncing).toBe(true)

    await act(async () => { hookApi?.triggerManualSync() })
    await flush(0)
    expect(postCount).toBe(1)
  })

  it('manual sync is not swallowed by a stale cache entry: it re-reads the authoritative state first (A176)', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    expect(postCount).toBe(1)
    const id = [...server.keys()][0]
    expect(hookApi?.isSyncing).toBe(true)

    // The request finished on the server, but the frontend cache still holds
    // the last polled non-terminal state (no poll has run since). A manual
    // trigger must re-check authoritatively instead of trusting the cache.
    server.get(id)!.state = 'complete'
    await act(async () => { hookApi?.triggerManualSync() })
    await flush(0)
    await flush(0)
    expect(postCount).toBe(2)
  })

  it('manual sync still blocks when the authoritative re-read says the request is active (A176)', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    expect(postCount).toBe(1)
    expect(hookApi?.isSyncing).toBe(true)

    await act(async () => { hookApi?.triggerManualSync() })
    await flush(0)
    expect(postCount).toBe(1)
  })

  it('scope switch: the old request completion does not clear the new scope spinner; switching back restores state', async () => {
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-a', email: 'a@x.test' } })
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    expect(postCount).toBe(1)
    const idA = [...server.keys()][0]
    expect(hookApi?.isSyncing).toBe(true)

    // Switch to scope B and start its own sync manually.
    await act(async () => {
      useMailStore.setState({ view: { type: 'account', accountId: 'acc-b', email: 'b@x.test' } })
    })
    await flush(0)
    await act(async () => { hookApi?.triggerManualSync() })
    await flush(0)
    await flush(0)
    expect(postCount).toBe(2)
    const idB = [...server.keys()][1]
    expect(hookApi?.currentRequestId).toBe(idB)
    expect(hookApi?.isSyncing).toBe(true)

    // A finishes on the server while B is on screen: B keeps spinning and
    // A's request is not polled under B's view.
    server.get(idA)!.state = 'complete'
    const aGetsWhileAway = getCount(idA)
    await flush(4_000)
    expect(hookApi?.isSyncing).toBe(true)
    expect(getCount(idA)).toBe(aGetsWhileAway)
    expect(getCount(idB)).toBeGreaterThanOrEqual(1)

    // Back to A: its own request state is restored and read authoritatively.
    await act(async () => {
      useMailStore.setState({ view: { type: 'account', accountId: 'acc-a', email: 'a@x.test' } })
    })
    await flush(0)
    await flush(2_000)
    expect(hookApi?.currentRequestId).toBe(idA)
    expect(hookApi?.isSyncing).toBe(false)
    expect(postCount).toBe(2)
  })

  it('unmount stops polling', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    const id = [...server.keys()][0]
    await flush(2_000)
    expect(getCount(id)).toBeGreaterThanOrEqual(1)
    expect(hookApi?.isSyncing).toBe(true)

    cleanup()
    const settledCount = getCount(id)
    await flush(10_000)
    expect(getCount(id)).toBe(settledCount)
  })

  it('hidden page pauses polling; becoming visible re-reads the authoritative state first', async () => {
    await render(createElement(Harness))
    await flush(0)
    await flush(0)
    const id = [...server.keys()][0]
    expect(hookApi?.isSyncing).toBe(true)

    await act(async () => {
      setVisibility('hidden')
      document.dispatchEvent(new Event('visibilitychange'))
    })
    const hiddenCount = getCount(id)
    await flush(6_000)
    expect(getCount(id)).toBe(hiddenCount)
    expect(hookApi?.isSyncing).toBe(true)

    server.get(id)!.state = 'complete'
    await act(async () => {
      setVisibility('visible')
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await flush(0)
    expect(getCount(id)).toBeGreaterThan(hiddenCount)
    expect(hookApi?.isSyncing).toBe(false)
  })

  it('reload recovery: adopts the scope\u2019s recent unfinished request from the list endpoint instead of posting a new one', async () => {
    server.set('req-old', { id: 'req-old', state: 'running' })
    listResult = [{ id: 'req-old', state: 'running' }]

    await render(createElement(Harness))
    await flush(0)
    await flush(0)

    expect(listCalls().length).toBeGreaterThanOrEqual(1)
    expect(listCalls()[0].url).toContain('limit=50')
    expect(postCount).toBe(0)
    expect(hookApi?.currentRequestId).toBe('req-old')
    expect(hookApi?.isSyncing).toBe(true)

    server.get('req-old')!.state = 'complete'
    await flush(2_000)
    expect(hookApi?.isSyncing).toBe(false)
    expect(getCount('req-old')).toBeGreaterThanOrEqual(1)
  })
})
