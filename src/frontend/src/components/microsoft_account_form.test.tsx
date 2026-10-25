import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AccountDialog from './settings_account_form'
import { cleanup, render, changeSelect, typeInto, click, waitFor } from '../test/render'
import { __resetCsrfForTests } from '../api/client'

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); __resetCsrfForTests() })

it.each([false, true])('Microsoft browser login saves a verified result (edit=%s)', async edit => {
  const requests: { url: string; method: string; body: Record<string, unknown> }[] = []
  const open = vi.fn(() => ({ opener: {} }))
  vi.stubGlobal('open', open)
  const account = { id: 'graph-1', email: 'verified@outlook.com', provider: 'graph', account_type: 'graph',
    status: 'active', sync_status: 'auth_failed', sync_enabled: false, oauth_tenant: 'consumers' }
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    requests.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : {} })
    let value: unknown = {}
    if (url.includes('/api/auth/me')) value = { csrf_token: 'test-csrf' }
    else if (url.includes('/oauth/metadata')) value = { provider: 'microsoft', runtime_mode: 'desktop',
      default_client_type: 'public', redirect_uri: 'http://localhost:23456/api/accounts/oauth/callback/microsoft',
      callback_path: '/api/accounts/oauth/callback/microsoft', origin_configured: true }
    else if (url.includes('/oauth/active')) value = { flow: null }
    else if (url.endsWith('/oauth/start')) value = { flow_id: 'ms-flow', provider: 'microsoft', intent: edit ? 'reauthorize' : 'create',
      method: 'authorization_code', status: 'pending', auth_url: 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize',
      client_type: 'public', redirect_uri: 'http://localhost:23456/api/accounts/oauth/callback/microsoft', expires_at: Date.now() / 1000 + 600 }
    else if (url.includes('/oauth/flows/ms-flow')) value = { flow_id: 'ms-flow', provider: 'microsoft', intent: edit ? 'reauthorize' : 'create',
      method: 'authorization_code', status: 'authorized', verified_email: 'verified@outlook.com', client_type: 'public' }
    return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
  }))
  const saved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog account={edit ? account : undefined} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={saved} />)
  if (!edit) await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await waitFor(() => expect((container.querySelector('#account-redirect-uri') as HTMLInputElement).value).toContain('localhost:23456'))
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  for (const text of ['New registration', 'Allow public client flows', 'secret ID', '不能在门户直接查看', 'localhost', 'offline_access', '注册权限']) {
    expect(container.querySelector('dialog[aria-labelledby="credential-help-title"]')?.textContent).toContain(text)
  }
  await click(container.querySelector('button[aria-label="关闭凭据帮助"]'))
  if (!edit) await typeInto(container.querySelector('#account-client-id'), 'own-client-id')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === (edit ? '重新授权' : '使用 Microsoft 登录'))!)
  expect(open).toHaveBeenCalledWith(expect.stringContaining('login.microsoftonline.com'), '_blank')
  window.dispatchEvent(new Event('focus'))
  await waitFor(() => expect(container.textContent).toContain('已完成 Microsoft 授权：verified@outlook.com'))
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(saved).toHaveBeenCalled())
  const write = requests.find(r => r.method === (edit ? 'PATCH' : 'POST') && r.url.endsWith(edit ? '/api/accounts/graph-1' : '/api/accounts'))
  expect(write?.body).toMatchObject({ oauth_flow_id: 'ms-flow' })
  expect(write?.body.credentials).toBeUndefined()
})

it('device code needs no callback or Secret, copies only the short code, polls and cancels', async () => {
  const requests: { url: string; body: Record<string, unknown> }[] = []
  const open = vi.fn()
  let pollAttempts = 0
  vi.stubGlobal('open', open)
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    requests.push({ url, body: init.body ? JSON.parse(String(init.body)) : {} })
    let value: unknown = {}
    if (url.includes('/api/auth/me')) value = { csrf_token: 'test-csrf' }
    else if (url.includes('/oauth/metadata')) value = { provider: 'microsoft', runtime_mode: 'web', default_client_type: 'confidential',
      callback_path: '/api/accounts/oauth/callback/microsoft', redirect_uri: null, origin_configured: false, notice: '缺少回调' }
    else if (url.includes('/oauth/active')) value = { flow: null }
    else if (url.endsWith('/oauth/start')) value = { flow_id: 'device-flow', provider: 'microsoft', intent: 'create',
      method: 'device_code', tenant: 'common', status: 'pending', auth_url: 'https://microsoft.com/devicelogin',
      client_type: 'public', redirect_uri: '', user_code: 'ABCD-EFGH', verification_uri: 'https://microsoft.com/devicelogin', expires_at: Date.now() / 1000 + 600 }
    else if (url.endsWith('/poll')) {
      pollAttempts += 1
      return new Response(JSON.stringify({ detail: '设备码轮询间隔尚未到达，请稍后重试。' }), {
        status: 429,
        headers: { 'content-type': 'application/json', 'Retry-After': '5' },
      })
    }
    return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
  }))
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await changeSelect(container.querySelector('#account-oauth-method'), 'device_code')
  expect(container.querySelector('#account-client-secret')).toBeNull()
  expect(container.querySelector('#account-redirect-uri')).toBeNull()
  await typeInto(container.querySelector('#account-client-id'), 'own-device-client')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '获取设备验证码')!)
  expect(container.textContent).toContain('ABCD-EFGH')
  expect(container.textContent).toContain('剩余')
  expect(open).not.toHaveBeenCalled()
  expect(requests.find(r => r.url.endsWith('/oauth/start'))?.body).toMatchObject({ method: 'device_code', client_type: 'public' })
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '复制验证码')!)
  expect(writeText).toHaveBeenCalledWith('ABCD-EFGH')
  const link = Array.from(container.querySelectorAll('a')).find(a => a.textContent === '打开微软登录页')!
  expect(link.href).toBe('https://microsoft.com/devicelogin')
  window.dispatchEvent(new Event('focus'))
  await waitFor(() => expect(requests.some(r => r.url.endsWith('/poll'))).toBe(true))
  await new Promise(resolve => setTimeout(resolve, 1200))
  expect(pollAttempts).toBe(1)
  expect(container.textContent).not.toContain('设备码轮询间隔尚未到达')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '取消授权')!)
  await waitFor(() => expect(requests.some(r => r.url.endsWith('/cancel'))).toBe(true))
  expect(container.textContent).not.toContain('ABCD-EFGH')
  expect(localStorage.length).toBe(0)
})

it.each([
  ['graph', false, false], ['graph', true, false], ['graph', false, true],
  ['gmail', false, false], ['gmail', true, false], ['gmail', false, true],
] as const)('legacy %s web account saves only explicit client config (move=%s, editType=%s)', async (provider, move, editType) => {
  const patches: Record<string, unknown>[] = []
  const oauthProvider = provider === 'graph' ? 'microsoft' : 'google'
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    let result: unknown = {}
    if (url.includes('/api/auth/me')) result = { csrf_token: 'csrf' }
    else if (url.includes('/oauth/active')) result = { flow: null }
    else if (url.includes('/oauth/metadata')) result = { provider: oauthProvider, runtime_mode: 'web',
      default_client_type: 'confidential', redirect_uri: `https://mail.example.test/api/accounts/oauth/callback/${oauthProvider}`,
      callback_path: `/api/accounts/oauth/callback/${oauthProvider}`, origin_configured: true }
    else if (init.method === 'PATCH') patches.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify(result), { headers: { 'content-type': 'application/json' } })
  }))
  const account = { id: 'legacy-account', email: 'legacy@example.com', provider, account_type: provider,
    status: 'active', sync_status: 'idle', sync_enabled: true }
  const { container } = await render(<AccountDialog account={account}
    groups={[{ id: 'target-group', name: '新分组', account_count: 0, sort_order: 0 }]} groupsAvailable
    onClose={vi.fn()} onSaved={vi.fn(async () => {})} />)
  await waitFor(() => expect((container.querySelector('#account-redirect-uri') as HTMLInputElement).value).toContain('https://mail.example.test'))
  expect((container.querySelector('#account-client-type') as HTMLSelectElement).value).toBe('public')
  if (editType) {
    await changeSelect(container.querySelector('#account-client-type'), 'confidential')
    await typeInto(container.querySelector('#account-client-secret'), 'operator-secret')
  }
  if (move) await changeSelect(container.querySelector('#account-group'), 'target-group')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(patches).toHaveLength(1))
  expect(patches[0]).toEqual({
    ...(move ? { group_id: 'target-group' } : {}),
    ...(editType ? { config: { oauth_client_type: 'confidential' }, credentials: { client_secret: 'operator-secret' } } : {}),
  })
})
