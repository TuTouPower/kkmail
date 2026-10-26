import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AccountDialog from './settings_account_form'
import { cleanup, render, changeSelect, typeInto, click, waitFor } from '../test/render'
import { __resetCsrfForTests } from '../api/client'

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); __resetCsrfForTests() })

// p056 replacement note: the previous parametrized "browser login saves a
// verified result (edit=false)" case asserted the OLD flat Microsoft
// add-account form (manual Client ID/Secret fields + flow start). Adding a
// Microsoft account now uses the simplified redirect-URL exchange below, so
// that case was replaced wholesale; the reauthorization (edit) case is kept
// here because existing Graph accounts still use the flow system.
it('Microsoft browser login reauthorizes an existing Graph account (edit)', async () => {
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
    else if (url.endsWith('/oauth/start')) value = { flow_id: 'ms-flow', provider: 'microsoft', intent: 'reauthorize',
      method: 'authorization_code', status: 'pending', auth_url: 'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize',
      client_type: 'public', redirect_uri: 'http://localhost:23456/api/accounts/oauth/callback/microsoft', expires_at: Date.now() / 1000 + 600 }
    else if (url.includes('/oauth/flows/ms-flow')) value = { flow_id: 'ms-flow', provider: 'microsoft', intent: 'reauthorize',
      method: 'authorization_code', status: 'authorized', verified_email: 'verified@outlook.com', client_type: 'public' }
    return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
  }))
  const saved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog account={account} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={saved} />)
  await waitFor(() => expect((container.querySelector('#account-redirect-uri') as HTMLInputElement).value).toContain('localhost:23456'))
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  // p056: Microsoft help is now the concise 3-step redirect-URL guidance.
  const helpDialog = container.querySelector('dialog[aria-labelledby="credential-help-title"]')!
  expect([...helpDialog.querySelectorAll('ol li')]).toHaveLength(3)
  for (const text of ['微软授权登录', '打不开的 localhost 地址', '地址栏', '换取 Token 并添加']) {
    expect(helpDialog.textContent).toContain(text)
  }
  expect(helpDialog.textContent).not.toContain('New registration')
  await click(container.querySelector('button[aria-label="关闭凭据帮助"]'))
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '重新授权')!)
  expect(open).toHaveBeenCalledWith(expect.stringContaining('login.microsoftonline.com'), '_blank')
  window.dispatchEvent(new Event('focus'))
  await waitFor(() => expect(container.textContent).toContain('已完成 Microsoft 授权：verified@outlook.com'))
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(saved).toHaveBeenCalled())
  const write = requests.find(r => r.method === 'PATCH' && r.url.endsWith('/api/accounts/graph-1'))
  expect(write?.body).toMatchObject({ oauth_flow_id: 'ms-flow' })
  expect(write?.body.credentials).toBeUndefined()
})

// p056 replacement note: the previous device-code test drove the OLD flat
// add-account form. Device-code login is no longer offered when adding an
// account (simplified redirect exchange instead); it remains available for
// reauthorizing an existing Graph account, which is what this test covers.
it('device code reauthorization needs no callback or Secret, copies only the short code, polls and cancels', async () => {
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
    else if (url.endsWith('/oauth/start')) value = { flow_id: 'device-flow', provider: 'microsoft', intent: 'reauthorize',
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
  const account = { id: 'graph-device-1', email: 'device@outlook.com', provider: 'graph', account_type: 'graph',
    status: 'active', sync_status: 'idle', sync_enabled: true }
  const { container } = await render(<AccountDialog account={account} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-oauth-method'), 'device_code')
  expect(container.querySelector('#account-client-secret')).toBeNull()
  expect(container.querySelector('#account-redirect-uri')).toBeNull()
  await typeInto(container.querySelector('#account-client-id'), 'own-device-client')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '重新授权')!)
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
] as const)('legacy %s web account saves only explicit client config (move=%s, editType=%s)', async (provider, move, editType) => {
  const patches: Record<string, unknown>[] = []
  const oauthProvider = 'microsoft'
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

// --- p056: simplified Microsoft onboarding (add account) -------------------

const msGroups = [{ id: 'grp-1', name: '工作组', account_count: 0, sort_order: 0 }]

function stubMicrosoftShell(exchange?: (body: Record<string, unknown>) => Response) {
  const exchanges: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'test-csrf' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/oauth/active')) return new Response(JSON.stringify({ flow: null }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/oauth/metadata')) return new Response(JSON.stringify({ provider: 'microsoft', runtime_mode: 'web', default_client_type: 'confidential', redirect_uri: null, callback_path: '/api/accounts/oauth/callback/microsoft', origin_configured: false, notice: '自托管网页部署需配置可信 HTTPS 公网 Origin（MAIL_CORE_PUBLIC_ORIGIN）' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/oauth/exchange-redirect-url')) {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      exchanges.push(body)
      if (exchange) return exchange(body)
      return new Response(JSON.stringify({ id: 'new-ms', email: 'real@outlook.com', provider: 'graph', status: 'active', sync_status: 'idle', sync_enabled: true, account_type: 'graph' }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { headers: { 'content-type': 'application/json' } })
  }))
  return exchanges
}

it('Microsoft add form initial state shows only email, group, auth button and collapsed advanced options', async () => {
  stubMicrosoftShell()
  const { container } = await render(<AccountDialog groups={msGroups} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  expect(container.querySelector('#account-email')).not.toBeNull()
  expect(container.querySelector('#account-group')).not.toBeNull()
  expect(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '微软授权登录')).toBeTruthy()
  // No developer fields from the old flat form, and no origin hard block.
  for (const id of ['account-client-secret', 'account-refresh-token', 'account-client-type', 'account-tenant', 'account-oauth-method', 'account-redirect-uri', 'account-token-uri', 'account-scope']) {
    expect(container.querySelector(`#${id}`)).toBeNull()
  }
  expect(container.textContent).not.toContain('MAIL_CORE_PUBLIC_ORIGIN')
  expect(container.querySelector('button[type="submit"]')).toBeNull()
  const advanced = container.querySelector('details.settings-advanced') as HTMLDetailsElement
  expect(advanced).not.toBeNull()
  expect(advanced.open).toBe(false)
  expect(advanced.querySelector('#account-client-id')).not.toBeNull()
  expect(advanced.querySelector('#account-ms-redirect-uri')).not.toBeNull()
  expect((advanced.querySelector('#account-ms-redirect-uri') as HTMLInputElement).value).toBe('http://localhost:8080')
})

it('clicking Microsoft auth opens the spec authorize URL and switches to the paste panel', async () => {
  stubMicrosoftShell()
  const open = vi.fn((..._args: unknown[]) => ({ opener: {} }))
  vi.stubGlobal('open', open)
  const { container } = await render(<AccountDialog groups={msGroups} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await typeInto(container.querySelector('#account-email'), 'me@outlook.com')
  await changeSelect(container.querySelector('#account-group'), 'grp-1')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '微软授权登录')!)
  expect(open).toHaveBeenCalledTimes(1)
  const url = new URL(String(open.mock.calls[0][0]))
  expect(`${url.origin}${url.pathname}`).toBe('https://login.microsoftonline.com/common/oauth2/v2.0/authorize')
  expect(url.searchParams.get('client_id')).toBe('9e5f94bc-e8a4-4e73-b8be-63364c29d753')
  expect(url.searchParams.get('response_type')).toBe('code')
  expect(url.searchParams.get('response_mode')).toBe('query')
  expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:8080')
  expect(url.searchParams.get('scope')).toBe('https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read offline_access')
  expect(url.searchParams.get('login_hint')).toBe('me@outlook.com')
  expect(url.searchParams.get('prompt')).toBe('select_account')
  expect(url.searchParams.get('state')).toBeTruthy()
  // Paste panel: guidance steps + input + actions.
  expect(container.textContent).toContain('打不开的网址')
  expect(container.textContent).toContain('复制浏览器地址栏的完整网址')
  const input = container.querySelector('#account-ms-redirect-url') as HTMLInputElement
  expect(input).not.toBeNull()
  expect(input.placeholder).toBe('请粘贴地址栏中的完整重定向链接...')
  for (const label of ['换取 Token 并添加', '重新打开授权页面', '返回上一步']) {
    expect(Array.from(container.querySelectorAll('button')).find(b => b.textContent === label)).toBeTruthy()
  }
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '重新打开授权页面')!)
  expect(open).toHaveBeenCalledTimes(2)
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '返回上一步')!)
  expect(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '微软授权登录')).toBeTruthy()
  expect(container.querySelector('#account-ms-redirect-url')).toBeNull()
})

// REPLACED (client-id consistency): the original version of this test
// asserted the exchange payload was exactly {redirected_url, email,
// group_id} -- no client_id, because the form only sent one when the
// user typed it. That omission was the bug: with the field empty, the
// authorize step used the frontend's hardcoded id while the backend
// exchanged with its own MICROSOFT_CLIENT_ID env override. The payload
// now always carries the id the authorize step used, so the test is
// replaced as a whole with the payload expectation extended by
// client_id (the built-in id here, since this shell's metadata reports
// no override).
it('pasting a redirect URL calls the exchange API and reports success via onSaved', async () => {
  const exchanges = stubMicrosoftShell()
  vi.stubGlobal('open', vi.fn(() => ({ opener: {} })))
  const saved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog groups={msGroups} groupsAvailable onClose={vi.fn()} onSaved={saved} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await typeInto(container.querySelector('#account-email'), 'me@outlook.com')
  await changeSelect(container.querySelector('#account-group'), 'grp-1')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '微软授权登录')!)
  await typeInto(container.querySelector('#account-ms-redirect-url'), 'http://localhost:8080/?code=abc123&state=xyz')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '换取 Token 并添加')!)
  await waitFor(() => expect(saved).toHaveBeenCalledWith('grp-1'))
  expect(exchanges).toHaveLength(1)
  expect(exchanges[0]).toEqual({
    redirected_url: 'http://localhost:8080/?code=abc123&state=xyz',
    email: 'me@outlook.com',
    group_id: 'grp-1',
    client_id: '9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  })
})

it('authorize and exchange both use the client id reported by OAuth metadata', async () => {
  const exchanges: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf-test' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/oauth/active')) return new Response(JSON.stringify({ flow: null }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/oauth/metadata')) return new Response(JSON.stringify({ provider: 'microsoft', runtime_mode: 'web', default_client_type: 'confidential', redirect_uri: null, callback_path: '/api/accounts/oauth/callback/microsoft', origin_configured: false, notice: 'n/a', microsoft_client_id: 'server-effective-client' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/oauth/exchange-redirect-url')) {
      exchanges.push(JSON.parse(String(init.body)) as Record<string, unknown>)
      return new Response(JSON.stringify({ id: 'new-ms', email: 'real@outlook.com', provider: 'graph', status: 'active', sync_status: 'idle', sync_enabled: true, account_type: 'graph' }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { headers: { 'content-type': 'application/json' } })
  }))
  const open = vi.fn((..._args: unknown[]) => ({ opener: {} }))
  vi.stubGlobal('open', open)
  const saved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog groups={msGroups} groupsAvailable onClose={vi.fn()} onSaved={saved} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await typeInto(container.querySelector('#account-email'), 'me@outlook.com')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '微软授权登录')!)
  expect(open).toHaveBeenCalledTimes(1)
  const url = new URL(String(open.mock.calls[0][0]))
  expect(url.searchParams.get('client_id')).toBe('server-effective-client')
  await typeInto(container.querySelector('#account-ms-redirect-url'), 'http://localhost:8080/?code=abc123&state=xyz')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '换取 Token 并添加')!)
  await waitFor(() => expect(saved).toHaveBeenCalled())
  expect(exchanges).toHaveLength(1)
  expect(exchanges[0].client_id).toBe('server-effective-client')
})

it('an exchange error renders the readable message inline under the input', async () => {
  stubMicrosoftShell(() => new Response(JSON.stringify({ detail: '链接中未找到授权码 (code)，请确保复制的是授权完成后的完整地址' }), { status: 400, headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('open', vi.fn(() => ({ opener: {} })))
  const saved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog groups={msGroups} groupsAvailable onClose={vi.fn()} onSaved={saved} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '微软授权登录')!)
  await typeInto(container.querySelector('#account-ms-redirect-url'), 'http://localhost:8080/')
  await click(Array.from(container.querySelectorAll('button')).find(b => b.textContent === '换取 Token 并添加')!)
  await waitFor(() => expect(container.querySelector('#account-ms-redirect-url')?.parentElement?.parentElement?.querySelector('[role="alert"]')?.textContent ?? container.querySelector('[role="alert"]')?.textContent).toContain('未找到授权码'))
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('请确保复制的是授权完成后的完整地址')
  expect(container.querySelector('[role="alert"]')?.textContent).not.toContain('MAIL_CORE')
  expect(saved).not.toHaveBeenCalled()
})
