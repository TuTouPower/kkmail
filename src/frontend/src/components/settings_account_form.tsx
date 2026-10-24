import { useEffect, useRef, useState } from 'react'
import { CircleHelp, X } from 'lucide-react'
import { api, type AccountSummary } from '../api/client'
import type { GroupItem } from '../api/queries'
import { errorMessage } from '../lib/actions'
import { vendors, inferVendor, defaultProtocol, type Vendor, type Protocol } from '../lib/account_providers'
import CredentialHelp from './credential_help'

/** Native modal traps focus; cleanup restores the control that opened it. */
export default function AccountDialog({ account, groups, groupsAvailable, onClose, onSaved }: {
  account?: AccountSummary
  groups: GroupItem[]
  groupsAvailable: boolean
  onClose: () => void
  onSaved: (groupId: string) => Promise<void>
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const busyRef = useRef(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [email, setEmail] = useState(account?.email || '')
  const [provider, setProvider] = useState<'imap' | 'gmail' | 'graph'>(account?.provider === 'gmail' || account?.provider === 'graph' ? account.provider : 'imap')
  const [host, setHost] = useState(account?.imap_config?.imap_host || '')
  const [port, setPort] = useState(String(account?.imap_config?.imap_port || (account?.imap_config?.use_ssl === false ? 143 : 993)))
  const [ssl, setSsl] = useState(account?.imap_config?.use_ssl !== false)
  const [password, setPassword] = useState('')
  const initialVendor = account?.provider_profile && account.provider_profile in vendors ? account.provider_profile as Vendor : account?.provider === 'graph' ? 'microsoft' : account?.provider === 'gmail' ? 'google' : inferVendor(account?.email || '')
  const [vendor, setVendor] = useState<Vendor>(initialVendor)
  const manualVendor = useRef(!!account)
  const connectionEdited = useRef(false)
  const [username, setUsername] = useState(account?.imap_config?.imap_user || '')
  const [oauth, setOauth] = useState({ client_id: '', refresh_token: '', client_secret: '', token_uri: '', scope: '' })
  const [clientType, setClientType] = useState(account?.oauth_client_type || 'public')
  const [help, setHelp] = useState(false)
  const changeVendor = (next: Vendor, manual = true) => {
    if (manual) manualVendor.current = true
    if (next === vendor) return
    setVendor(next)
    if (!account) setProvider(defaultProtocol(next))
    setPassword(''); setOauth({ client_id: '', refresh_token: '', client_secret: '', token_uri: '', scope: '' })
    if (!connectionEdited.current) { setHost(vendors[next].host); setPort('993'); setSsl(true) }
  }
  const [groupId, setGroupId] = useState(account?.group_id || '')

  useEffect(() => {
    const dialog = dialogRef.current!
    const previousFocus = document.activeElement
    dialog.showModal()
    emailRef.current?.focus()
    return () => {
      dialog.close()
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
    }
  }, [])

  return <dialog className="settings-dialog" ref={dialogRef} aria-labelledby="account-dialog-title" onCancel={event => {
    event.preventDefault()
    if (!busyRef.current || status) onClose()
  }}>
    <div className="settings-dialog-head"><div><h2 id="account-dialog-title">{account ? '编辑账户' : '添加账户'}</h2><p>{account ? '修改邮箱连接配置。已保存凭据不会回显，留空表示保持不变。' : '配置邮箱连接，凭据加密保存且不会回显。'}</p></div><button type="button" className="settings-icon-button" aria-label={`关闭${account ? '编辑' : '添加'}账户`} disabled={busy && !status} onClick={onClose}><X size={18} /></button></div>
    <form data-ui="ST05" onSubmit={async event => {
      event.preventDefault()
      if (busyRef.current) return
      if (provider === 'imap' && !host.trim()) { setStatus('请输入 IMAP 服务器地址'); return }
      let credentials: Record<string, unknown> = {}
      if (provider === 'imap' && password) credentials = { password }
      if (provider !== 'imap') credentials = Object.fromEntries(Object.entries(oauth).filter(([, value]) => value !== ''))
      const config = {
        ...(provider === 'imap' ? { imap_host: host.trim(), imap_port: Number(port), use_ssl: ssl, ...(username.trim() ? { imap_user: username.trim() } : account?.imap_config?.imap_user ? { imap_user: '' } : {}) } : {}),
        ...(!account || vendor !== initialVendor ? { provider_profile: vendor } : {}),
        ...(provider !== 'imap' && (!account || clientType !== (account.oauth_client_type || 'public')) ? { oauth_client_type: clientType } : {}),
      }
      const parsedPort = Number(port)
      if (provider === 'imap' && (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65535)) { setStatus('端口必须为 1–65535 的整数'); return }
      busyRef.current = true
      setBusy(true)
      setStatus('')
      let saved = false
      try {
        if (account) {
          await api.updateAccount(account.id, {
            ...(Object.keys(config).length ? { config } : {}),
            ...(groupId !== (account.group_id || '') && groupsAvailable ? (groupId ? { group_id: groupId } : { clear_group: true }) : {}),
            ...(Object.keys(credentials).length ? { credentials } : {}),
          })
        } else {
          await api.addAccount({
            email: email.trim(), provider,
            ...(groupId && groupsAvailable ? { group_id: groupId } : {}),
            credentials,
            ...(Object.keys(config).length ? { config } : {}),
          })
        }
        saved = true
        await onSaved(groupId)
      } catch (error) {
        const action = account ? '更新' : '添加'
        setStatus(saved ? `账户已${action}，刷新失败：${errorMessage(error)}。请关闭窗口后刷新页面。` : errorMessage(error, `账户${action}失败`))
      } finally {
        busyRef.current = saved
        setBusy(saved)
      }
    }}>
      <fieldset disabled={busy}>
        <label className="settings-field" htmlFor="account-email"><span>邮箱地址</span><input ref={emailRef} id="account-email" name="email" type="email" autoComplete="email" value={email} onChange={event => { setEmail(event.target.value); if (!manualVendor.current) changeVendor(inferVendor(event.target.value), false) }} readOnly={!!account} required placeholder="name@example.com" maxLength={320} /></label>
        <label className="settings-field" htmlFor="account-vendor"><span>邮箱供应商</span><select id="account-vendor" value={vendor} disabled={!!account} onChange={event => changeVendor(event.target.value as Vendor)}>{Object.entries(vendors).map(([key, info]) => <option key={key} value={key}>{info.label}</option>)}</select></label>
        <div className="settings-fields"><label className="settings-field" htmlFor="account-provider"><span>连接方式</span><select id="account-provider" value={provider} disabled={!!account} onChange={event => { setProvider(event.target.value as Protocol); setPassword(''); setOauth({ client_id: '', refresh_token: '', client_secret: '', token_uri: '', scope: '' }) }}>{vendor === 'microsoft' ? <option value="graph">Microsoft OAuth / Graph</option> : vendor === 'google' ? <><option value="gmail">Google OAuth / Gmail API</option><option value="imap">IMAP 应用专用密码</option></> : <option value="imap">IMAP</option>}</select></label><label className="settings-field" htmlFor="account-group"><span>所属分组</span><select id="account-group" value={groupId} onChange={event => setGroupId(event.target.value)} disabled={!groupsAvailable}><option value="">不加入分组</option>{groups.map(group => <option value={group.id} key={group.id}>{group.name}</option>)}</select></label></div>
        <button type="button" className="settings-button" aria-label="如何获取账户凭据" onClick={() => setHelp(true)}><CircleHelp size={16} /> 如何获取凭据</button>
        {/@(proton\.me|protonmail\.com|pm\.me|protonmail\.ch)$/i.test(email.trim()) && <p className="settings-notice">Proton 不能使用登录密码直接连接公网 IMAP。需要付费 Proton Mail Bridge，本产品尚未集成；不会自动放开本机或私网连接。</p>}
        {vendor === 'zoho' && <p className="settings-notice">实际主机以账号内数据中心配置为准；付费企业通常使用 imappro.zoho.com，部分免费计划不支持 IMAP。启用两步验证或 SAML 时使用应用密码。</p>}
        {provider === 'imap' ? <>
          <label className="settings-field" htmlFor="account-imap-host"><span>IMAP 服务器</span><input id="account-imap-host" name="imap_host" value={host} onChange={event => { connectionEdited.current = true; setHost(event.target.value) }} required placeholder="imap.example.com" /></label>
          <div className="settings-fields"><label className="settings-field" htmlFor="account-imap-port"><span>端口</span><input id="account-imap-port" name="imap_port" type="number" min={1} max={65535} required value={port} onChange={event => { connectionEdited.current = true; setPort(event.target.value) }} /></label><label className="settings-checkbox"><input id="account-imap-ssl" name="use_ssl" type="checkbox" checked={ssl} onChange={event => { connectionEdited.current = true; setSsl(event.target.checked); if (port === '993' && !event.target.checked) setPort('143'); else if (port === '143' && event.target.checked) setPort('993') }} />SSL / TLS</label></div>
          <label className="settings-field" htmlFor="account-username"><span>IMAP 登录名</span><input id="account-username" value={username} onChange={event => setUsername(event.target.value)} placeholder={email || '默认完整邮箱地址'} /></label>
          <label className="settings-field" htmlFor="account-password"><span>{vendors[vendor].credential}</span><input id="account-password" name="mailbox-password" type="password" autoComplete="new-password" value={password} required={!account} onChange={event => setPassword(event.target.value)} placeholder={account ? '留空保持已保存密码不变' : '邮箱服务商提供的密码或授权码'} /></label>
        </> : <>
          <p className="settings-notice">{account ? '已保存凭据不会回显。只填写需要更新的字段，留空保持不变。' : '使用已有 OAuth 凭据连接；获取方法见帮助说明。'}</p>
          <label className="settings-field" htmlFor="account-client-type"><span>OAuth 应用类型</span><select id="account-client-type" value={clientType} onChange={event => setClientType(event.target.value)}><option value="public">公共客户端 / 桌面应用</option><option value="confidential">机密客户端 / Web 应用</option></select></label>
          {(['client_id', 'refresh_token', 'client_secret'] as const).map(key => <label className="settings-field" key={key} htmlFor={`account-${key.replaceAll('_', '-')}`}><span>{key === 'client_id' ? 'Client ID' : key === 'refresh_token' ? 'Refresh Token' : 'Client Secret'}</span><input id={`account-${key.replaceAll('_', '-')}`} type={key === 'client_id' ? 'text' : 'password'} autoComplete="off" value={oauth[key]} required={!account && (key !== 'client_secret' || clientType === 'confidential')} onChange={event => setOauth(old => ({ ...old, [key]: event.target.value }))} placeholder={account ? '留空保持不变' : key === 'client_secret' ? '公共客户端通常不需要；机密客户端填写 secret value' : ''} /></label>)}
          <details className="settings-advanced"><summary>高级 OAuth 配置</summary>
            <label className="settings-field" htmlFor="account-token-uri"><span>令牌端点（留空使用默认）</span><input id="account-token-uri" value={oauth.token_uri} onChange={event => setOauth(old => ({ ...old, token_uri: event.target.value }))} placeholder={provider === 'graph' ? 'https://login.microsoftonline.com/common/oauth2/v2.0/token' : 'https://oauth2.googleapis.com/token'} /></label>
            {provider === 'graph' && <label className="settings-field" htmlFor="account-tenant"><span>Microsoft 租户</span><input id="account-tenant" placeholder="common / consumers / organizations / 租户 ID" onChange={event => { const tenant = event.target.value.trim(); if (/^[a-zA-Z0-9.-]+$/.test(tenant)) setOauth(old => ({ ...old, token_uri: `https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token` })) }} /></label>}
            <label className="settings-field" htmlFor="account-scope"><span>已授权范围（不会扩大原授权）</span><input id="account-scope" value={oauth.scope} onChange={event => setOauth(old => ({ ...old, scope: event.target.value }))} /></label>
          </details>
        </>}
      </fieldset>
      {status && <div className="settings-feedback is-error" role="alert">{status}</div>}
      <div className="settings-dialog-actions"><button type="button" className="settings-button" onClick={onClose} disabled={busy && !status}>取消</button><button type="submit" className="settings-button is-primary" disabled={busy}>{busy && !status ? '正在保存…' : account ? '保存修改' : '添加'}</button></div>
    </form>
    {help && <CredentialHelp vendor={vendor} protocol={provider} onClose={() => setHelp(false)} />}
  </dialog>
}
