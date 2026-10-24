import { useState } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AccountDialog from './settings_account_form'
import SettingsPage from './SettingsModal'
import { cleanup, render, changeSelect, typeInto, click, waitFor } from '../test/render'
import { __resetCsrfForTests } from '../api/client'
import { queryClient } from '../api/queries'

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); __resetCsrfForTests() })

it('offers Google IMAP and OAuth, Microsoft OAuth only, and contextual credential help', async () => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  await changeSelect(container.querySelector('#account-provider'), 'imap')
  expect((container.querySelector('#account-imap-host') as HTMLInputElement).value).toBe('imap.gmail.com')
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  expect(container.querySelector('dialog[aria-labelledby="credential-help-title"]')?.textContent).toContain('两步验证')
  await click(container.querySelector('button[aria-label="关闭凭据帮助"]'))
  expect(container.querySelector('dialog[open]')).not.toBeNull()
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  expect(container.querySelector('#account-imap-host')).toBeNull()
  expect(container.querySelector('#account-client-id')).not.toBeNull()
  expect(container.querySelector('#account-credentials')).toBeNull()
})

it('does not replace manually entered host when the address changes', async () => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await typeInto(container.querySelector('#account-imap-host'), 'custom.example.test')
  await typeInto(container.querySelector('#account-username'), 'independent-login')
  await typeInto(container.querySelector('#account-email'), 'hello@qq.com')
  expect((container.querySelector('#account-imap-host') as HTMLInputElement).value).toBe('custom.example.test')
  expect((container.querySelector('#account-username') as HTMLInputElement).value).toBe('independent-login')
})

it('updates a single OAuth field without echoing or replacing saved secrets', async () => {
  const calls: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    if (String(input).includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    calls.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify({ id: 'a' }))
  }))
  const account = { id: 'a', email: 'a@outlook.com', provider: 'graph', status: 'active', sync_status: 'idle', sync_enabled: true, account_type: 'graph' }
  const { container } = await render(<AccountDialog account={account} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await typeInto(container.querySelector('#account-refresh-token'), 'new-refresh')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(calls).toHaveLength(1))
  expect(calls[0].credentials).toEqual({ refresh_token: 'new-refresh' })
})


it.each([
  ['qq', 'imap.qq.com', '客户端授权码', '开启 IMAP'],
  ['netease_163', 'imap.163.com', '客户端授权码', '通用客户端授权码'],
  ['netease_126', 'imap.126.com', '客户端授权码', '通用客户端授权码'],
  ['netease_yeah', 'imap.yeah.net', '客户端授权码', '通用客户端授权码'],
  ['icloud', 'imap.mail.me.com', '应用专用密码', '双重认证'],
  ['yahoo', 'imap.mail.yahoo.com', '应用专用密码', 'App Password'],
  ['zoho', 'imap.zoho.com', '密码或应用专用密码', 'imappro.zoho.com'],
])('renders provider %s presets and actionable help', async (vendor, host, credential, help) => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), vendor)
  expect((container.querySelector('#account-imap-host') as HTMLInputElement).value).toBe(host)
  expect((container.querySelector('#account-imap-port') as HTMLInputElement).value).toBe('993')
  expect((container.querySelector('#account-imap-ssl') as HTMLInputElement).checked).toBe(true)
  expect(container.querySelector('label[for="account-password"]')?.textContent).toBe(credential)
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  const dialog = container.querySelector('dialog[aria-labelledby="credential-help-title"]')!
  expect(dialog.textContent).toContain(help)
  expect(dialog.querySelector('a')?.getAttribute('href')).toMatch(/^https:/)
  if (vendor === 'zoho') for (const text of ['个人', '付费企业', '数据中心', '免费计划', '两步验证', 'SAML']) expect(dialog.textContent).toContain(text)
})

it.each([
  ['google', ['gmail.modify', 'gmail.send', '不额外申请', 'https://mail.google.com/', 'Web 应用', 'Desktop app', '7 天', '自有 Google 应用配置', '不会代办']],
  ['microsoft', ['Mail.ReadWrite', 'offline_access', '后台继续同步', 'secret ID', 'Application (client) ID']],
])('explains provider %s authorization requirements through the help dialog', async (vendor, expected) => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), vendor as string)
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  const text = container.querySelector('dialog[aria-labelledby="credential-help-title"]')!.textContent
  for (const item of expected as string[]) expect(text).toContain(item)
})

it('clears credentials across supplier and authentication changes and sends only current fields', async () => {
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    if (String(input).includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    writes.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify({ id: 'new' }))
  }))
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await typeInto(container.querySelector('#account-email'), 'x@gmail.com')
  await typeInto(container.querySelector('#account-client-id'), 'google-client')
  await typeInto(container.querySelector('#account-refresh-token'), 'google-token')
  await typeInto(container.querySelector('#account-client-secret'), 'google-secret')
  await changeSelect(container.querySelector('#account-provider'), 'imap')
  await typeInto(container.querySelector('#account-password'), 'google-imap-password')
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  for (const id of ['client-id', 'refresh-token', 'client-secret']) expect((container.querySelector(`#account-${id}`) as HTMLInputElement).value).toBe('')
  await typeInto(container.querySelector('#account-email'), 'x@outlook.com')
  await typeInto(container.querySelector('#account-client-id'), 'ms-client')
  await typeInto(container.querySelector('#account-refresh-token'), 'ms-refresh')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ provider: 'graph', credentials: { client_id: 'ms-client', refresh_token: 'ms-refresh' } })
  expect(JSON.stringify(writes)).not.toMatch(/google-|imap_host|password/)
})

it('discards credentials when the dialog is closed and reopened', async () => {
  function Harness() {
    const [open, setOpen] = useState(true)
    return <>{open ? <AccountDialog groups={[]} groupsAvailable onClose={() => setOpen(false)} onSaved={vi.fn()} /> : <button onClick={() => setOpen(true)}>重新打开</button>}</>
  }
  const { container } = await render(<Harness />)
  await typeInto(container.querySelector('#account-password'), 'must-disappear')
  for (const storage of [localStorage, sessionStorage]) expect(Object.keys(storage).map(key => storage.getItem(key)).join('')).not.toContain('must-disappear')
  await click(container.querySelector('button[aria-label="关闭添加账户"]'))
  await click(container.querySelector('button'))
  expect((container.querySelector('#account-password') as HTMLInputElement).value).toBe('')
  expect(Object.keys(localStorage).map(key => localStorage.getItem(key)).join('')).not.toContain('must-disappear')
  expect(Object.keys(sessionStorage).map(key => sessionStorage.getItem(key)).join('')).not.toContain('must-disappear')
})

it('supports Google OAuth redirect sign-in, popup-blocked fallback, and atomic account creation', async () => {
  const requests: Array<{ url: string; method: string; body?: Record<string, unknown> }> = []
  let flowStatus: 'pending' | 'authorized' = 'pending'
  vi.stubGlobal('open', vi.fn(() => null))
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    const method = (init.method || 'GET').toUpperCase()
    const body = init.body ? JSON.parse(String(init.body)) : undefined
    requests.push({ url, method, body })
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/api/accounts/oauth/metadata')) {
      return new Response(JSON.stringify({
        provider: 'google',
        runtime_mode: 'web',
        default_client_type: 'public',
        redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
        callback_path: '/api/accounts/oauth/callback/google',
        origin_configured: true,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/active')) {
      return new Response(JSON.stringify({ flow: null }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/start')) {
      return new Response(JSON.stringify({
        flow_id: 'flow-create-1',
        provider: 'google',
        intent: 'create',
        status: 'pending',
        auth_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=s1',
        redirect_uri: 'http://127.0.0.1:18765/api/accounts/oauth/callback/google',
        client_type: 'public',
        expires_at: 9999999999,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/flows/flow-create-1')) {
      return new Response(JSON.stringify({
        flow_id: 'flow-create-1',
        provider: 'google',
        intent: 'create',
        group_id: 'g-1',
        client_type: 'public',
        client_id: 'desktop-cid',
        status: flowStatus,
        verified_email: flowStatus === 'authorized' ? 'verified@gmail.com' : null,
        error: null,
        redirect_uri: 'http://127.0.0.1:18765/api/accounts/oauth/callback/google',
        expires_at: 9999999999,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/accounts') && method === 'POST') {
      return new Response(JSON.stringify({ id: 'created-gmail-id', email: 'verified@gmail.com' }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({ ok: true }), { headers: { 'content-type': 'application/json' } })
  }))

  const onSaved = vi.fn(async () => {})
  const { container } = await render(
    <AccountDialog
      groups={[{ id: 'g-1', name: '主力组', account_count: 0, sort_order: 0 }]}
      groupsAvailable
      onClose={vi.fn()}
      onSaved={onSaved}
    />,
  )
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  await changeSelect(container.querySelector('#account-group'), 'g-1')
  await waitFor(() => expect((container.querySelector('#account-redirect-uri') as HTMLInputElement).value).toBe('https://mail.example.com/api/accounts/oauth/callback/google'))

  // Clipboard copy button: when clipboard unavailable, reports manual fallback (never false positive)
  Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '复制回调地址')!)
  expect(container.textContent).toContain('请手动复制上方回调地址')

  // When clipboard.writeText is available, copies exact redirect URI and reports success
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '复制回调地址')!)
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://mail.example.com/api/accounts/oauth/callback/google'))
  expect(container.textContent).toContain('已复制回调地址')

  // Missing Client ID is explicitly reported before starting OAuth
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '使用 Google 登录')!)
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Client ID')

  await typeInto(container.querySelector('#account-client-id'), 'desktop-cid')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '使用 Google 登录')!)
  await waitFor(() => expect(container.textContent).toContain('浏览器拦截了授权窗口'))

  flowStatus = 'authorized'
  window.dispatchEvent(new Event('focus'))
  await waitFor(() => expect(container.textContent).toContain('已完成 Google 授权：verified@gmail.com'))
  expect((container.querySelector('#account-email') as HTMLInputElement).value).toBe('verified@gmail.com')

  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith('g-1'))
  const createCall = requests.find(r => r.url.endsWith('/api/accounts') && r.method === 'POST')
  expect(createCall?.body).toMatchObject({
    email: 'verified@gmail.com',
    provider: 'gmail',
    group_id: 'g-1',
    oauth_flow_id: 'flow-create-1',
  })
})

it.each(['failed', 'expired'] as const)('supports Gmail API reauthorization retry after %s and PATCH save with oauth_flow_id', async initialStatus => {
  const requests: Array<{ url: string; method: string; body?: Record<string, unknown> }> = []
  let reauthStatus: 'failed' | 'expired' | 'authorized' = initialStatus
  const openedWindow = { opener: {} as unknown }
  vi.stubGlobal('open', vi.fn(() => openedWindow as unknown as Window))
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    const method = (init.method || 'GET').toUpperCase()
    const body = init.body ? JSON.parse(String(init.body)) : undefined
    requests.push({ url, method, body })
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/api/accounts/oauth/metadata')) {
      return new Response(JSON.stringify({
        provider: 'google',
        runtime_mode: 'web',
        default_client_type: 'confidential',
        redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
        callback_path: '/api/accounts/oauth/callback/google',
        origin_configured: true,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/active')) {
      return new Response(JSON.stringify({ flow: null }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/start')) {
      return new Response(JSON.stringify({
        flow_id: 'flow-reauth-1',
        provider: 'google',
        intent: 'reauthorize',
        status: 'pending',
        auth_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=reauth',
        redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
        client_type: 'confidential',
        expires_at: 9999999999,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/flows/flow-reauth-1') && !url.endsWith('/cancel')) {
      return new Response(JSON.stringify({
        flow_id: 'flow-reauth-1',
        provider: 'google',
        intent: 'reauthorize',
        account_id: 'acc-gmail-1',
        client_type: 'confidential',
        client_id: 'saved-cid',
        status: reauthStatus,
        verified_email: reauthStatus === 'authorized' ? 'existing@gmail.com' : null,
        error: reauthStatus === 'authorized' ? null : initialStatus === 'expired' ? '授权流程已过期，请重新发起' : '回调地址不匹配（redirect_uri_mismatch）',
        redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
        expires_at: 9999999999,
      }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({ ok: true, id: 'acc-gmail-1' }), { headers: { 'content-type': 'application/json' } })
  }))

  const account = {
    id: 'acc-gmail-1',
    email: 'existing@gmail.com',
    provider: 'gmail',
    status: 'active',
    sync_status: 'auth_failed',
    sync_enabled: true,
    account_type: 'gmail',
    provider_profile: 'google',
    oauth_client_type: 'confidential',
  }
  const onClose = vi.fn()
  const onSaved = vi.fn(async () => {})
  const { container } = await render(
    <AccountDialog account={account} groups={[]} groupsAvailable onClose={onClose} onSaved={onSaved} />,
  )

  // Help dialog works in edit mode as well (AC-013)
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  expect(container.querySelector('dialog[aria-labelledby="credential-help-title"]')?.textContent).toContain('gmail.modify')
  await click(container.querySelector('button[aria-label="关闭凭据帮助"]'))

  // 1st attempt fails: displays redacted error alert, clears opener, allows cancel and retry
  const reauthBtn = Array.from(container.querySelectorAll('button')).find(b => b.textContent === '重新授权')!
  await click(reauthBtn)
  expect(openedWindow.opener).toBeNull()
  window.dispatchEvent(new Event('focus'))
  await waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain(initialStatus === 'expired' ? '授权流程已过期' : 'redirect_uri_mismatch'))

  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '取消授权')!)
  await waitFor(() => expect(requests.some(r => r.url.endsWith('/api/accounts/oauth/flows/flow-reauth-1/cancel'))).toBe(true))

  // 2nd attempt succeeds and clicking "保存修改" sends PATCH with oauth_flow_id
  reauthStatus = 'authorized'
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '重新授权')!)
  window.dispatchEvent(new Event('focus'))
  await waitFor(() => expect(container.textContent).toContain('已完成 Google 授权：existing@gmail.com'))

  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  const patchCall = requests.find(r => r.url.includes('/api/accounts/acc-gmail-1') && r.method === 'PATCH')
  expect(patchCall?.body).toMatchObject({ oauth_flow_id: 'flow-reauth-1' })
})

it('restores active Google OAuth draft on #oauth-return in SettingsPage and AccountDialog', async () => {
  queryClient.clear()
  window.location.hash = '#oauth-return'
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/api/accounts/oauth/active')) {
      return new Response(JSON.stringify({
        flow: {
          flow_id: 'flow-return-1',
          provider: 'google',
          intent: 'create',
          account_id: null,
          group_id: 'grp-restore',
          client_type: 'confidential',
          client_id: 'restored-client-id',
          status: 'authorized',
          verified_email: 'restored@gmail.com',
          error: null,
          redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
          expires_at: 9999999999,
        },
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/metadata')) {
      return new Response(JSON.stringify({
        provider: 'google',
        runtime_mode: 'web',
        default_client_type: 'confidential',
        redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
        callback_path: '/api/accounts/oauth/callback/google',
        origin_configured: true,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (new URL(url, window.location.origin).pathname === '/api/accounts') {
      return new Response(JSON.stringify({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/groups')) {
      return new Response(JSON.stringify({ groups: [{ id: 'grp-restore', name: '恢复分组', account_count: 0, sort_order: 0 }] }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/settings')) {
      return new Response(JSON.stringify({ settings: {} }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { headers: { 'content-type': 'application/json' } })
  }))

  const { container } = await render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  )
  await waitFor(() => expect(container.textContent).toContain('已完成 Google 授权：restored@gmail.com'))
  expect((container.querySelector('#account-email') as HTMLInputElement).value).toBe('restored@gmail.com')
  expect((container.querySelector('#account-group') as HTMLSelectElement).value).toBe('grp-restore')
  expect((container.querySelector('#account-client-id') as HTMLInputElement).value).toBe('restored-client-id')
  expect(window.location.hash).toBe('')
})
