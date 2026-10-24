import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AccountDialog from './settings_account_form'
import { cleanup, render, changeSelect, typeInto, click, waitFor } from '../test/render'
import { __resetCsrfForTests } from '../api/client'

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
  ['google', ['gmail.modify', 'gmail.send', '不额外申请', 'https://mail.google.com/']],
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
