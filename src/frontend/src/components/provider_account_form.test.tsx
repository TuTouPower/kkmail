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

it('Google onboarding offers only IMAP app-password: no OAuth fields, Gmail presets prefilled, Microsoft still OAuth only', async () => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  // Connection method is locked to IMAP app-password: it is the only option.
  const providerSelect = container.querySelector('#account-provider') as HTMLSelectElement
  expect(providerSelect.value).toBe('imap')
  expect([...providerSelect.options].map(option => option.value)).toEqual(['imap'])
  expect([...providerSelect.options].map(option => option.textContent)).toEqual(['IMAP（应用专用密码）'])
  // No OAuth developer fields anywhere in the Google add-account form.
  for (const id of ['account-client-id', 'account-client-secret', 'account-refresh-token', 'account-token-uri', 'account-scope', 'account-redirect-uri', 'account-client-type']) {
    expect(container.querySelector(`#${id}`)).toBeNull()
  }
  for (const label of ['Client ID', 'Client Secret', 'Refresh Token', 'OAuth 回调地址', '令牌端点', 'Token Endpoint', 'Redirect URI']) {
    expect(container.textContent).not.toContain(label)
  }
  // Gmail server params are prefilled (imap.gmail.com / 993 / SSL), tucked into 高级网络设置.
  const advanced = [...container.querySelectorAll('details.settings-advanced')].find(d => d.querySelector('summary')?.textContent === '高级网络设置')
  expect(advanced).toBeTruthy()
  expect(advanced!.querySelector('#account-imap-host')).not.toBeNull()
  expect((container.querySelector('#account-imap-host') as HTMLInputElement).value).toBe('imap.gmail.com')
  expect((container.querySelector('#account-imap-port') as HTMLInputElement).value).toBe('993')
  expect((container.querySelector('#account-imap-ssl') as HTMLInputElement).checked).toBe(true)
  // The password field is labelled/hinted as the 16-digit app password.
  expect(container.querySelector('label[for="account-password"]')?.textContent).toContain('应用专用密码')
  expect((container.querySelector('#account-password') as HTMLInputElement).placeholder).toContain('应用专用密码')
  expect((container.querySelector('#account-password') as HTMLInputElement).placeholder).toContain('16')
  // Microsoft still offers OAuth only.
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  expect(container.querySelector('#account-imap-host')).toBeNull()
  expect(container.querySelector('#account-client-id')).not.toBeNull()
  expect(container.querySelector('#account-credentials')).toBeNull()
})

it('submitting the Google form creates an IMAP account with the Gmail params', async () => {
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if ((init.method || 'GET') !== 'GET') writes.push({ url, body: JSON.parse(String(init.body)) })
    return new Response(JSON.stringify({ id: 'new' }))
  }))
  const onSaved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={onSaved} />)
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  await typeInto(container.querySelector('#account-email'), 'someone@gmail.com')
  await typeInto(container.querySelector('#account-password'), 'abcd efgh ijkl mnop')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  expect(writes).toHaveLength(1)
  expect(writes[0].url).toMatch(/\/api\/accounts$/)
  expect(writes[0].body).toMatchObject({
    email: 'someone@gmail.com',
    provider: 'imap',
    credentials: { password: 'abcd efgh ijkl mnop' },
    config: { imap_host: 'imap.gmail.com', imap_port: 993, use_ssl: true, provider_profile: 'google' },
  })
  expect(JSON.stringify(writes)).not.toMatch(/client_id|client_secret|refresh_token|token_uri|oauth/)
})

it('CredentialHelp for Google renders the 3 app-password steps and the apppasswords link, with no Cloud Console/CASA content', async () => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  const dialog = container.querySelector('dialog[aria-labelledby="credential-help-title"]')!
  const steps = [...dialog.querySelectorAll('ol li')]
  expect(steps).toHaveLength(3)
  expect(steps[0].textContent).toContain('两步验证')
  expect(steps[1].textContent).toContain('https://myaccount.google.com/apppasswords')
  expect(steps[2].textContent).toContain('16 位')
  expect(steps[2].textContent).toContain('kkmail')
  const link = [...dialog.querySelectorAll('a')].find(a => a.getAttribute('href') === 'https://myaccount.google.com/apppasswords')
  expect(link).toBeTruthy()
  for (const banned of ['Google Cloud', 'Cloud Console', 'CASA', 'OAuth', 'Gmail API']) {
    expect(dialog.textContent).not.toContain(banned)
  }
})

// p057 replacement note: this test previously typed into #account-username
// while the field was always rendered flat. p057 hides it behind the
// 「使用自定义登录名」 toggle, so the test was replaced wholesale to check
// the toggle first; its original assertions (manually entered host and
// username survive an email change) are unchanged.
it('does not replace manually entered host when the address changes', async () => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await typeInto(container.querySelector('#account-imap-host'), 'custom.example.test')
  await click(container.querySelector('#account-use-custom-username'))
  await typeInto(container.querySelector('#account-username'), 'independent-login')
  await typeInto(container.querySelector('#account-email'), 'hello@qq.com')
  expect((container.querySelector('#account-imap-host') as HTMLInputElement).value).toBe('custom.example.test')
  expect((container.querySelector('#account-username') as HTMLInputElement).value).toBe('independent-login')
})

it('p057: hides the IMAP username by default and submits without a custom imap_user', async () => {
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if ((init.method || 'GET') !== 'GET') writes.push({ url, body: JSON.parse(String(init.body)) })
    return new Response(JSON.stringify({ id: 'new' }))
  }))
  const onSaved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={onSaved} />)
  const toggle = container.querySelector('#account-use-custom-username') as HTMLInputElement
  expect(toggle).not.toBeNull()
  expect(toggle.checked).toBe(false)
  expect(container.querySelector('label[for="account-use-custom-username"]')?.textContent).toContain('使用自定义登录名')
  expect(container.querySelector('#account-username')).toBeNull()
  await typeInto(container.querySelector('#account-email'), 'person@example.test')
  await typeInto(container.querySelector('#account-imap-host'), 'imap.example.test')
  await typeInto(container.querySelector('#account-password'), 'secret-password')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  expect(writes).toHaveLength(1)
  expect(writes[0].url).toMatch(/\/api\/accounts$/)
  expect(writes[0].body).toMatchObject({
    email: 'person@example.test',
    provider: 'imap',
    credentials: { password: 'secret-password' },
    config: { imap_host: 'imap.example.test', imap_port: 993, use_ssl: true },
  })
  expect(writes[0].body.config as Record<string, unknown>).not.toHaveProperty('imap_user')
  expect(JSON.stringify(writes)).not.toContain('imap_user')
})

it('p057: checking the custom-login toggle reveals the username field and submits its value', async () => {
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if ((init.method || 'GET') !== 'GET') writes.push({ url, body: JSON.parse(String(init.body)) })
    return new Response(JSON.stringify({ id: 'new' }))
  }))
  const onSaved = vi.fn(async () => {})
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={onSaved} />)
  expect(container.querySelector('#account-username')).toBeNull()
  await click(container.querySelector('#account-use-custom-username'))
  expect((container.querySelector('#account-use-custom-username') as HTMLInputElement).checked).toBe(true)
  expect(container.querySelector('#account-username')).not.toBeNull()
  await typeInto(container.querySelector('#account-email'), 'person@example.test')
  await typeInto(container.querySelector('#account-imap-host'), 'imap.example.test')
  await typeInto(container.querySelector('#account-username'), 'sys-user-42')
  await typeInto(container.querySelector('#account-password'), 'secret-password')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  expect(writes).toHaveLength(1)
  expect(writes[0].body).toMatchObject({
    email: 'person@example.test',
    provider: 'imap',
    config: { imap_host: 'imap.example.test', imap_user: 'sys-user-42' },
  })
})

it('p057: editing an account with a differing stored imap_user auto-checks the toggle and shows the value', async () => {
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if ((init.method || 'GET') !== 'GET') writes.push({ url, body: JSON.parse(String(init.body)) })
    return new Response(JSON.stringify({ id: 'acc-custom' }))
  }))
  const onSaved = vi.fn(async () => {})
  const account = {
    id: 'acc-custom',
    email: 'person@example.test',
    provider: 'imap',
    status: 'active',
    sync_status: 'idle',
    sync_enabled: true,
    account_type: 'imap',
    imap_config: { imap_host: 'imap.example.test', imap_port: 993, use_ssl: true, imap_user: 'sys-user-42' },
  }
  const { container } = await render(<AccountDialog account={account} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={onSaved} />)
  expect((container.querySelector('#account-use-custom-username') as HTMLInputElement).checked).toBe(true)
  expect((container.querySelector('#account-username') as HTMLInputElement).value).toBe('sys-user-42')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  expect(writes).toHaveLength(1)
  expect(writes[0].url).toMatch(/\/api\/accounts\/acc-custom$/)
  expect(writes[0].body).toMatchObject({ config: { imap_user: 'sys-user-42' } })
})

it('p057: editing an account whose stored imap_user equals its email keeps the toggle off and clears it on save', async () => {
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if ((init.method || 'GET') !== 'GET') writes.push({ url, body: JSON.parse(String(init.body)) })
    return new Response(JSON.stringify({ id: 'acc-same' }))
  }))
  const onSaved = vi.fn(async () => {})
  const account = {
    id: 'acc-same',
    email: 'person@example.test',
    provider: 'imap',
    status: 'active',
    sync_status: 'idle',
    sync_enabled: true,
    account_type: 'imap',
    imap_config: { imap_host: 'imap.example.test', imap_port: 993, use_ssl: true, imap_user: 'person@example.test' },
  }
  const { container } = await render(<AccountDialog account={account} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={onSaved} />)
  expect((container.querySelector('#account-use-custom-username') as HTMLInputElement).checked).toBe(false)
  expect(container.querySelector('#account-username')).toBeNull()
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  expect(writes).toHaveLength(1)
  // '' is the form's existing clear convention: the backend removes the
  // stored imap_user and falls back to the email address.
  expect(writes[0].body).toMatchObject({ config: { imap_user: '' } })
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

// p056 replacement note: the previous test here ("validates a custom OAuth
// token URI before submitting account credentials (Microsoft)") asserted the
// OLD flat Microsoft add-account form — manual Client ID / Refresh Token /
// token_uri fields submitted as credentials. That behavior was removed by
// the simplified redirect-URL onboarding (covered in
// microsoft_account_form.test.tsx), so the test was removed wholesale rather
// than having its expectations rewritten in place.

it('releases save controls when the account write succeeds but refresh fails', async () => {
  const writes: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if (url.endsWith('/api/accounts/oauth/active')) return new Response(JSON.stringify({ flow: null }))
    if (url.endsWith('/api/accounts/acc-1') && init.method === 'PATCH') {
      writes.push(url)
      return new Response(JSON.stringify({ id: 'acc-1' }))
    }
    return new Response(JSON.stringify({}))
  }))

  const onSaved = vi.fn()
    .mockRejectedValueOnce(new Error('refresh failed'))
    .mockResolvedValue(undefined)
  const account = {
    id: 'acc-1',
    email: 'a@example.test',
    provider: 'imap',
    status: 'active',
    sync_status: 'idle',
    sync_enabled: true,
    account_type: 'imap',
    imap_config: { imap_host: 'imap.example.test', imap_port: 993, use_ssl: true },
  }
  const { container } = await render(
    <AccountDialog account={account} groups={[]} groupsAvailable onClose={vi.fn()} onSaved={onSaved} />,
  )
  const submit = container.querySelector('button[type="submit"]') as HTMLButtonElement

  await click(submit)
  await waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain('刷新失败'))
  expect((container.querySelector('fieldset') as HTMLFieldSetElement).disabled).toBe(false)
  expect(submit.disabled).toBe(false)

  await click(submit)
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(onSaved).toHaveBeenCalledTimes(2)
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

// p055: the Google row was removed wholesale — Google help is now the
// app-password guide, covered by the dedicated CredentialHelp test above.
// p056: the Microsoft row was replaced wholesale — the help dialog now shows
// the concise 3-step redirect-URL guidance instead of the Azure registration
// walkthrough asserted before.
it('explains provider microsoft authorization through the concise 3-step help dialog', async () => {
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  const dialog = container.querySelector('dialog[aria-labelledby="credential-help-title"]')!
  const steps = [...dialog.querySelectorAll('ol li')]
  expect(steps).toHaveLength(3)
  expect(steps[0].textContent).toContain('微软授权登录')
  expect(steps[1].textContent).toContain('localhost')
  expect(steps[1].textContent).toContain('地址栏')
  expect(steps[2].textContent).toContain('换取 Token 并添加')
  expect(dialog.textContent).not.toContain('New registration')
})

// p056 replacement note: the previous version of this test typed manual
// Microsoft credentials (client id / refresh token / secret) into the OLD
// flat add-account form and submitted them. That form was removed; the test
// was replaced wholesale with the same vendor-switch hygiene asserted
// against the simplified Microsoft form and the Google IMAP form.
it('clears credentials across supplier changes (Microsoft simplified form)', async () => {
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    if (String(input).includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }))
    if ((init.method || 'GET') === 'GET') return new Response(JSON.stringify({ flow: null }))
    writes.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify({ id: 'new' }))
  }))
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  // The only credential-adjacent field left is the collapsed custom Client ID.
  await typeInto(container.querySelector('#account-client-id'), 'ms-client-1')
  expect(container.querySelector('#account-refresh-token')).toBeNull()
  expect(container.querySelector('#account-client-secret')).toBeNull()
  // Switching to Google shows the IMAP form (no OAuth fields carry over).
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  expect(container.querySelector('#account-client-id')).toBeNull()
  await typeInto(container.querySelector('#account-password'), 'google-imap-password')
  // Switching back to Microsoft clears the custom Client ID and the IMAP password.
  await changeSelect(container.querySelector('#account-vendor'), 'microsoft')
  expect((container.querySelector('#account-client-id') as HTMLInputElement).value).toBe('')
  // Submitting the Google form still sends only the current IMAP fields.
  await changeSelect(container.querySelector('#account-vendor'), 'google')
  await typeInto(container.querySelector('#account-email'), 'someone@gmail.com')
  await typeInto(container.querySelector('#account-password'), 'abcd efgh ijkl mnop')
  await click(container.querySelector('button[type="submit"]'))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ provider: 'imap', credentials: { password: 'abcd efgh ijkl mnop' } })
  expect(JSON.stringify(writes)).not.toMatch(/ms-client-1|client_id|refresh_token/)
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

  // Help dialog works in edit mode as well (AC-013). p055: Google help is the
  // app-password guide everywhere — no OAuth/Gmail-API content remains.
  await click(container.querySelector('button[aria-label="如何获取账户凭据"]'))
  expect(container.querySelector('dialog[aria-labelledby="credential-help-title"]')?.textContent).toContain('https://myaccount.google.com/apppasswords')
  expect(container.querySelector('dialog[aria-labelledby="credential-help-title"]')?.textContent).not.toContain('gmail.modify')
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

it('restores active Microsoft OAuth draft on #oauth-return in SettingsPage and AccountDialog', async () => {
  queryClient.clear()
  window.location.hash = '#oauth-return'
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/api/accounts/oauth/active')) {
      return new Response(JSON.stringify({
        flow: {
          flow_id: 'flow-return-1',
          provider: 'microsoft',
          intent: 'create',
          account_id: null,
          group_id: 'grp-restore',
          client_type: 'confidential',
          client_id: 'restored-client-id',
          status: 'authorized',
          verified_email: 'restored@outlook.com',
          error: null,
          redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/microsoft',
          expires_at: 9999999999,
        },
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/accounts/oauth/metadata')) {
      return new Response(JSON.stringify({
        provider: 'microsoft',
        runtime_mode: 'web',
        default_client_type: 'confidential',
        redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/microsoft',
        callback_path: '/api/accounts/oauth/callback/microsoft',
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
  await waitFor(() => expect(container.textContent).toContain('已完成 Microsoft 授权：restored@outlook.com'))
  expect((container.querySelector('#account-email') as HTMLInputElement).value).toBe('restored@outlook.com')
  expect((container.querySelector('#account-group') as HTMLSelectElement).value).toBe('grp-restore')
  expect((container.querySelector('#account-client-id') as HTMLInputElement).value).toBe('restored-client-id')
  expect(window.location.hash).toBe('')
})

it('ignores a stale Google OAuth create flow instead of resurrecting the OAuth form', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = String(input)
    if (url.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'csrf' }), { headers: { 'content-type': 'application/json' } })
    if (url.includes('/api/accounts/oauth/active')) {
      return new Response(JSON.stringify({
        flow: {
          flow_id: 'flow-stale-google',
          provider: 'google',
          intent: 'create',
          account_id: null,
          group_id: null,
          client_type: 'public',
          client_id: 'stale-client-id',
          status: 'authorized',
          verified_email: 'stale@gmail.com',
          error: null,
          redirect_uri: 'https://mail.example.com/api/accounts/oauth/callback/google',
          expires_at: 9999999999,
        },
      }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { headers: { 'content-type': 'application/json' } })
  }))
  const { container } = await render(<AccountDialog groups={[]} groupsAvailable onClose={vi.fn()} onSaved={vi.fn()} />)
  // Give the active-flow lookup a chance to (not) apply.
  await new Promise(resolve => setTimeout(resolve, 50))
  expect(container.querySelector('#account-client-id')).toBeNull()
  expect((container.querySelector('#account-email') as HTMLInputElement).value).toBe('')
  expect(container.textContent).not.toContain('已完成 Google 授权')
})
