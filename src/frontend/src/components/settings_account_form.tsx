import { useEffect, useRef, useState } from 'react'
import { CircleHelp, X } from 'lucide-react'
import { api, type AccountSummary, type ApiError, type OAuthFlowStatusOut, type OAuthMetadataOut } from '../api/client'
import type { GroupItem } from '../api/queries'
import { errorMessage } from '../lib/actions'
import { vendors, inferVendor, defaultProtocol, type Vendor, type Protocol } from '../lib/account_providers'
import { copyTextToClipboard } from '../lib/clipboard'
import { getDesktopPlatform } from '../lib/desktopShell'
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
  const initialProvider: 'imap' | 'gmail' | 'graph' = account?.provider === 'gmail'
    ? 'gmail'
    : account?.provider === 'graph'
      ? 'graph'
      : 'imap'
  const [provider, setProvider] = useState(initialProvider)
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
  const [clearClientSecret, setClearClientSecret] = useState(false)
  const [clientType, setClientType] = useState(account?.oauth_client_type || 'public')
  const clientTypeEdited = useRef(!!account?.oauth_client_type)
  const [oauthMethod, setOauthMethod] = useState<'authorization_code' | 'device_code'>('authorization_code')
  const [tenant, setTenant] = useState(account?.oauth_tenant || (account ? '' : 'common'))
  const [now, setNow] = useState(() => Date.now())
  const oauthProvider = provider === 'graph' ? 'microsoft' : 'google'
  const oauthLabel = provider === 'graph' ? 'Microsoft' : 'Google'
  const [help, setHelp] = useState(false)
  const [oauthMeta, setOauthMeta] = useState<OAuthMetadataOut | null>(null)
  const [oauthFlow, setOauthFlow] = useState<(OAuthFlowStatusOut & { auth_url?: string }) | null>(null)
  const [popupBlockedUrl, setPopupBlockedUrl] = useState('')
  const [copyTip, setCopyTip] = useState('')
  const flowRef = useRef<string | null>(null)
  const devicePollNotBeforeRef = useRef(0)

  const updateOauthFlow = (next: (OAuthFlowStatusOut & { auth_url?: string }) | null) => {
    if (flowRef.current !== next?.flow_id) devicePollNotBeforeRef.current = 0
    flowRef.current = next?.flow_id || null
    setOauthFlow(next)
  }

  const clearActiveFlow = (cancelRemote = true) => {
    const id = flowRef.current
    flowRef.current = null
    devicePollNotBeforeRef.current = 0
    setOauthFlow(null)
    setPopupBlockedUrl('')
    setCopyTip('')
    if (cancelRemote && id && typeof api.cancelOAuthFlow === 'function') {
      void api.cancelOAuthFlow(id).catch(() => {})
    }
  }

  const handleClose = () => {
    clearActiveFlow(true)
    onClose()
  }

  const changeVendor = (next: Vendor, manual = true) => {
    if (manual) manualVendor.current = true
    if (next === vendor) return
    clearActiveFlow(true)
    setVendor(next)
    if (!account) setProvider(defaultProtocol(next))
    setPassword(''); setOauth({ client_id: '', refresh_token: '', client_secret: '', token_uri: '', scope: '' }); setClearClientSecret(false)
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

  useEffect(() => {
    let cancelled = false
    if (typeof api.getActiveOAuthFlow === 'function') {
      void api.getActiveOAuthFlow().then(res => {
        if (cancelled || !res?.flow || typeof res.flow.flow_id !== 'string') return
        const flow = res.flow
        const matches = account ? (flow.intent === 'reauthorize' && flow.account_id === account.id) : flow.intent === 'create'
        if (!matches || !['google', 'microsoft'].includes(flow.provider)) return
        if (!account) {
          manualVendor.current = true
          setVendor(flow.provider === 'microsoft' ? 'microsoft' : 'google')
          setProvider(flow.provider === 'microsoft' ? 'graph' : 'gmail')
        }
        clientTypeEdited.current = true
        updateOauthFlow(flow)
        setClientType(flow.client_type)
        setOauthMethod(flow.method || 'authorization_code')
        if (flow.tenant) setTenant(flow.tenant)
        if (flow.group_id) setGroupId(flow.group_id)
        if (flow.client_id) setOauth(old => ({ ...old, client_id: old.client_id || flow.client_id }))
        if (!account && flow.verified_email) setEmail(flow.verified_email)
        if (flow.status === 'failed' && flow.error) setStatus(flow.error)
      }).catch(() => {})
    }
    return () => { cancelled = true }
  }, [account])

  useEffect(() => {
    if (provider === 'imap') return
    let cancelled = false
    if (typeof api.getOAuthMetadata === 'function') {
      void api.getOAuthMetadata(oauthProvider).then(meta => {
        if (cancelled || !meta || typeof meta.callback_path !== 'string') return
        setOauthMeta(meta)
        if (!account && !flowRef.current && !clientTypeEdited.current && (meta.default_client_type === 'public' || meta.default_client_type === 'confidential')) {
          setClientType(meta.default_client_type)
        }
      }).catch(() => {})
    }
    return () => { cancelled = true }
  }, [provider, account, oauthProvider])

  useEffect(() => {
    if (!oauthFlow || oauthFlow.status !== 'pending' || typeof api.getOAuthFlowStatus !== 'function') return
    let stopped = false
    const check = async () => {
      if (oauthFlow.method === 'device_code' && Date.now() < devicePollNotBeforeRef.current) return
      try {
        const next = await (oauthFlow.method === 'device_code' ? api.pollOAuthFlow(oauthFlow.flow_id) : api.getOAuthFlowStatus(oauthFlow.flow_id))
        if (stopped) return
        if (oauthFlow.method === 'device_code') devicePollNotBeforeRef.current = 0
        setOauthFlow(prev => prev && prev.flow_id === next.flow_id ? { ...prev, ...next } : prev)
        if (next.status === 'authorized') {
          if (!account && next.verified_email) setEmail(next.verified_email)
          setPopupBlockedUrl('')
          setStatus('')
        } else if ((next.status === 'failed' || next.status === 'expired') && next.error) {
          setStatus(next.error)
        }
      } catch (err) {
        if (!stopped && oauthFlow.method === 'device_code' && err && typeof err === 'object') {
          const apiError = err as ApiError
          if (apiError.status === 429) {
            devicePollNotBeforeRef.current = Date.now() + Math.max(1, apiError.retryAfterSeconds ?? 5) * 1000
            return
          }
        }
        if (!stopped) setStatus(errorMessage(err, `获取 ${oauthLabel} 授权状态失败`))
      }
    }
    const timer = window.setInterval(() => { void check() }, 1000)
    const onFocus = () => { void check() }
    window.addEventListener('focus', onFocus)
    return () => {
      stopped = true
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [oauthFlow, account, oauthLabel])

  useEffect(() => {
    if (oauthFlow?.method !== 'device_code' || oauthFlow.status !== 'pending') return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [oauthFlow?.method, oauthFlow?.status])

  const startOAuth = async () => {
    if (busyRef.current) return
    setStatus('')
    setPopupBlockedUrl('')
    const missing: string[] = []
    if (!account && !oauth.client_id.trim()) missing.push('Client ID')
    const device = provider === 'graph' && oauthMethod === 'device_code'
    const requiresSecret = !device && (clientType === 'confidential' || (provider === 'graph' && oauthMeta?.runtime_mode === 'web'))
    if (!account && requiresSecret && !oauth.client_secret.trim()) missing.push('Client Secret')
    if (!device && oauthMeta && !oauthMeta.origin_configured) missing.push('可信回调地址 (MAIL_CORE_PUBLIC_ORIGIN)')
    if (missing.length) {
      setStatus(`缺少 OAuth 配置项：${missing.join('、')}。请补齐配置或点击「如何获取凭据」查看步骤。`)
      return
    }
    busyRef.current = true
    setBusy(true)
    try {
      clearActiveFlow(true)
      const started = await api.startOAuthFlow({
        provider: oauthProvider,
        method: provider === 'graph' ? oauthMethod : 'authorization_code',
        ...(provider === 'graph' ? { tenant } : {}),
        intent: account ? 'reauthorize' : 'create',
        ...(account ? { account_id: account.id } : {}),
        ...(email.trim() ? { email_hint: email.trim() } : {}),
        ...(groupId && groupsAvailable ? { group_id: groupId } : {}),
        client_type: (device ? 'public' : clientType) as 'public' | 'confidential',
        ...(oauth.client_id.trim() ? { client_id: oauth.client_id.trim() } : {}),
        ...(!device && oauth.client_secret.trim() ? { client_secret: oauth.client_secret.trim() } : {}),
      })
      setNow(Date.now())
      updateOauthFlow({
        flow_id: started.flow_id,
        provider: started.provider,
        intent: started.intent,
        account_id: account?.id || null,
        group_id: groupId || null,
        client_type: started.client_type,
        client_id: oauth.client_id.trim(),
        status: 'pending',
        verified_email: null,
        error: null,
        redirect_uri: started.redirect_uri,
        expires_at: started.expires_at,
        method: started.method, tenant: started.tenant,
        user_code: started.user_code, verification_uri: started.verification_uri,
        auth_url: started.auth_url,
      })
      if (device) return
      const isDesktop = getDesktopPlatform() !== null || oauthMeta?.runtime_mode === 'desktop'
      const opened = typeof window.open === 'function' ? window.open(started.auth_url, '_blank') : null
      if (opened && typeof opened === 'object') {
        try { opened.opener = null } catch { /* ignore */ }
      } else if (!isDesktop) {
        setPopupBlockedUrl(started.auth_url)
      }
    } catch (err) {
      setStatus(errorMessage(err, `发起 ${oauthLabel} 登录授权失败`))
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const oauthAuthorized = provider !== 'imap' && oauthFlow?.status === 'authorized'
  const displayedRedirectUri = oauthFlow?.redirect_uri || oauthMeta?.redirect_uri || oauthMeta?.callback_path || `/api/accounts/oauth/callback/${oauthProvider}`

  return <dialog className="settings-dialog" ref={dialogRef} aria-labelledby="account-dialog-title" onCancel={event => {
    event.preventDefault()
    if (!busyRef.current || status) handleClose()
  }}>
    <div className="settings-dialog-head"><div><h2 id="account-dialog-title">{account ? '编辑账户' : '添加账户'}</h2><p>{account ? '修改邮箱连接配置。已保存凭据不会回显，留空表示保持不变。' : '配置邮箱连接，凭据加密保存且不会回显。'}</p></div><button type="button" className="settings-icon-button" aria-label={`关闭${account ? '编辑' : '添加'}账户`} disabled={busy && !status} onClick={handleClose}><X size={18} /></button></div>
    <form data-ui="ST05" onSubmit={async event => {
      event.preventDefault()
      if (busyRef.current) return
      if (provider === 'imap' && !host.trim()) { setStatus('请输入 IMAP 服务器地址'); return }
      if (provider !== 'imap' && !oauthAuthorized && oauth.token_uri !== '') {
        let tokenUri: URL
        try {
          tokenUri = new URL(oauth.token_uri)
        } catch {
          setStatus('令牌端点必须是有效的完整 URL')
          return
        }
        if (tokenUri.protocol !== 'https:') {
          setStatus('令牌端点必须使用 HTTPS')
          return
        }
      }
      let credentials: Record<string, unknown> = {}
      if (provider === 'imap' && password) credentials = { password }
      if (provider !== 'imap' && !oauthAuthorized) credentials = Object.fromEntries(Object.entries(oauth).filter(([, value]) => value !== ''))
      const config = {
        ...(provider === 'imap' ? { imap_host: host.trim(), imap_port: Number(port), use_ssl: ssl, ...(username.trim() ? { imap_user: username.trim() } : account?.imap_config?.imap_user ? { imap_user: '' } : {}) } : {}),
        ...(!account || vendor !== initialVendor ? { provider_profile: vendor } : {}),
        ...(provider !== 'imap' && (!account || (clientTypeEdited.current && clientType !== (account.oauth_client_type || 'public'))) ? { oauth_client_type: clientType } : {}),
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
            ...(oauthAuthorized && oauthFlow ? { oauth_flow_id: oauthFlow.flow_id } : Object.keys(credentials).length ? { credentials } : {}),
            ...(!oauthAuthorized && clearClientSecret ? { clear_credentials: ['client_secret'] } : {}),
          })
        } else {
          await api.addAccount({
            email: (oauthAuthorized && oauthFlow?.verified_email ? oauthFlow.verified_email : email).trim(),
            provider,
            ...(groupId && groupsAvailable ? { group_id: groupId } : {}),
            ...(oauthAuthorized && oauthFlow ? { oauth_flow_id: oauthFlow.flow_id } : { credentials }),
            ...(Object.keys(config).length ? { config } : {}),
          })
        }
        flowRef.current = null
        setOauthFlow(null)
        saved = true
        await onSaved(groupId)
      } catch (error) {
        const action = account ? '更新' : '添加'
        setStatus(saved ? `账户已${action}，刷新失败：${errorMessage(error)}。请关闭窗口后刷新页面。` : errorMessage(error, `账户${action}失败`))
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    }}>
      <fieldset disabled={busy}>
        <label className="settings-field" htmlFor="account-email"><span>邮箱地址</span><input ref={emailRef} id="account-email" name="email" type="email" autoComplete="email" value={email} onChange={event => { setEmail(event.target.value); if (!manualVendor.current) changeVendor(inferVendor(event.target.value), false) }} readOnly={!!account || oauthAuthorized} required={!oauthAuthorized} placeholder="name@example.com" maxLength={320} /></label>
        <label className="settings-field" htmlFor="account-vendor"><span>邮箱供应商</span><select id="account-vendor" value={vendor} disabled={!!account} onChange={event => changeVendor(event.target.value as Vendor)}>{Object.entries(vendors).map(([key, info]) => <option key={key} value={key}>{info.label}</option>)}</select></label>
        <div className="settings-fields"><label className="settings-field" htmlFor="account-provider"><span>连接方式</span><select id="account-provider" value={provider} disabled={!!account} onChange={event => { clearActiveFlow(true); setProvider(event.target.value as Protocol); setPassword(''); setOauth({ client_id: '', refresh_token: '', client_secret: '', token_uri: '', scope: '' }); setClearClientSecret(false) }}>{vendor === 'microsoft' ? <option value="graph">Microsoft OAuth / Graph</option> : vendor === 'google' ? <><option value="gmail">Google OAuth / Gmail API</option><option value="imap">IMAP 应用专用密码</option></> : <option value="imap">IMAP</option>}</select></label><label className="settings-field" htmlFor="account-group"><span>所属分组</span><select id="account-group" value={groupId} onChange={event => setGroupId(event.target.value)} disabled={!groupsAvailable}><option value="">不加入分组</option>{groups.map(group => <option value={group.id} key={group.id}>{group.name}</option>)}</select></label></div>
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
          <label className="settings-field" htmlFor="account-client-type"><span>OAuth 应用类型</span><select id="account-client-type" value={clientType} disabled={provider === 'graph' && oauthMethod === 'device_code'} onChange={event => { clientTypeEdited.current = true; clearActiveFlow(true); setClientType(event.target.value) }}><option value="public">公共客户端 / 桌面应用</option><option value="confidential">机密客户端 / Web 应用</option></select></label>
          {provider === 'graph' && <>
            <label className="settings-field" htmlFor="account-oauth-method"><span>Microsoft 登录方式</span><select id="account-oauth-method" value={oauthMethod} onChange={event => { clearActiveFlow(true); setOauthMethod(event.target.value as 'authorization_code' | 'device_code'); clientTypeEdited.current = true; if (event.target.value === 'device_code') { setClientType('public'); setOauth(old => ({ ...old, client_secret: '' })) } else setClientType(oauthMeta?.default_client_type || 'public') }}><option value="authorization_code">浏览器登录</option><option value="device_code">设备码登录</option></select></label>
            <label className="settings-field" htmlFor="account-tenant"><span>Microsoft 账号类型 / 租户</span><input id="account-tenant" list="microsoft-tenants" placeholder="留空复用已保存租户；新账户默认 common" value={tenant} onChange={event => { clearActiveFlow(true); setTenant(event.target.value) }} /><datalist id="microsoft-tenants"><option value="common">个人和组织账号</option><option value="consumers">个人 Outlook / Hotmail</option><option value="organizations">Microsoft 365 组织账号</option></datalist></label>
            <p className="settings-notice">设备码使用允许公共客户端流程的应用，无需回调地址或 Secret。Client ID 来自自有应用注册；两种登录均自动取得后台同步凭据。</p>
          </>}
          {<>
            {!(provider === 'graph' && oauthMethod === 'device_code') && <>
            <label className="settings-field" htmlFor="account-redirect-uri"><span>OAuth 回调地址（Redirect URI）</span><input id="account-redirect-uri" readOnly value={displayedRedirectUri} /></label></>}
            <div className="settings-dialog-actions">
              {!(provider === 'graph' && oauthMethod === 'device_code') && <button type="button" className="settings-button" onClick={async () => {
                try {
                  await copyTextToClipboard(displayedRedirectUri)
                  setCopyTip('已复制回调地址')
                } catch {
                  setCopyTip('请手动复制上方回调地址')
                }
              }}>复制回调地址</button>}
              <button type="button" className="settings-button is-primary" disabled={clearClientSecret} onClick={() => void startOAuth()}>{account ? '重新授权' : provider === 'graph' && oauthMethod === 'device_code' ? '获取设备验证码' : `使用 ${oauthLabel} 登录`}</button>
              {oauthFlow && <button type="button" className="settings-button" onClick={() => clearActiveFlow(true)}>取消授权</button>}
            </div>
            {oauthFlow?.method === 'device_code' && oauthFlow.status === 'pending' && <div className="settings-notice" role="status">
              <p>复制短验证码 → 打开微软官方验证页 → 输入代码并登录 → 返回此处等待确认。</p>
              <p>验证码：<strong>{oauthFlow.user_code}</strong> · 剩余 {Math.max(0, Math.ceil(oauthFlow.expires_at - now / 1000))} 秒</p>
              <p>{oauthFlow.verification_uri}</p>
              <button type="button" className="settings-button" onClick={async () => {
                try {
                  await copyTextToClipboard(oauthFlow.user_code || '')
                  setCopyTip('已复制验证码')
                } catch {
                  setCopyTip('复制失败，请手动复制验证码')
                }
              }}>复制验证码</button>
              <a href={oauthFlow.verification_uri || undefined} target="_blank" rel="noopener noreferrer">打开微软登录页</a>
            </div>}
            {copyTip && <p className="settings-notice" role="status">{copyTip}</p>}
            {!(provider === 'graph' && oauthMethod === 'device_code') && oauthMeta && !oauthMeta.origin_configured && oauthMeta.notice && <p className="settings-notice">{oauthMeta.notice}</p>}
            {popupBlockedUrl && <p className="settings-notice" role="status">浏览器拦截了授权窗口，请<a href={popupBlockedUrl} target="_blank" rel="noopener noreferrer">点击此处打开 {oauthLabel} 授权页面</a>。</p>}
            {oauthFlow?.status === 'pending' && <p className="settings-notice" role="status">正在等待 {oauthLabel} 授权完成…在浏览器完成同意后将自动同步状态。</p>}
            {oauthFlow?.status === 'authorized' && <p className="settings-feedback" role="status">已完成 {oauthLabel} 授权：{oauthFlow.verified_email}。请点击下方「{account ? '保存修改' : '添加'}」完成确认保存。</p>}
          </>}
          {(['client_id', 'refresh_token', 'client_secret'] as const).filter(key => !(provider === 'graph' && oauthMethod === 'device_code') || key === 'client_id').map(key => <label className="settings-field" key={key} htmlFor={`account-${key.replaceAll('_', '-')}`}><span>{key === 'client_id' ? 'Client ID' : key === 'refresh_token' ? 'Refresh Token' : 'Client Secret'}</span><input id={`account-${key.replaceAll('_', '-')}`} type={key === 'client_id' ? 'text' : 'password'} autoComplete="off" value={oauth[key]} required={!account && !oauthAuthorized && (key !== 'client_secret' || clientType === 'confidential')} onChange={event => { if (key !== 'refresh_token') clearActiveFlow(true); if (key === 'client_secret' && event.target.value) setClearClientSecret(false); setOauth(old => ({ ...old, [key]: event.target.value })) }} placeholder={account ? '留空保持不变' : key === 'refresh_token' ? (provider === 'gmail' ? '使用上方 Google 登录可自动获取，或手动粘贴已有 Refresh Token' : '') : key === 'client_secret' ? '公共客户端通常不需要；机密客户端填写 secret value' : ''} /></label>)}
          {account && <label className="settings-checkbox" htmlFor="account-clear-client-secret"><input id="account-clear-client-secret" type="checkbox" checked={clearClientSecret} disabled={!!oauthFlow} onChange={event => setClearClientSecret(event.target.checked)} />清除已保存的 Client Secret</label>}
          {clearClientSecret && <p className="settings-notice">清除操作会随“保存修改”生效；需要重新授权时，请先保存或取消清除。</p>}
          {clearClientSecret && clientType === 'confidential' && <p className="settings-notice">机密客户端必须保留 Client Secret；清除前请切换为公共客户端。</p>}
          <details className="settings-advanced"><summary>高级 OAuth 配置</summary>
            <label className="settings-field" htmlFor="account-token-uri"><span>令牌端点（留空使用默认）</span><input id="account-token-uri" value={oauth.token_uri} onChange={event => setOauth(old => ({ ...old, token_uri: event.target.value }))} placeholder={provider === 'graph' ? 'https://login.microsoftonline.com/common/oauth2/v2.0/token' : 'https://oauth2.googleapis.com/token'} /></label>
            <label className="settings-field" htmlFor="account-scope"><span>已授权范围（不会扩大原授权）</span><input id="account-scope" value={oauth.scope} onChange={event => setOauth(old => ({ ...old, scope: event.target.value }))} /></label>
          </details>
        </>}
      </fieldset>
      {status && <div className="settings-feedback is-error" role="alert">{status}</div>}
      <div className="settings-dialog-actions"><button type="button" className="settings-button" onClick={handleClose} disabled={busy && !status}>取消</button><button type="submit" className="settings-button is-primary" disabled={busy}>{busy && !status ? '正在保存…' : account ? '保存修改' : '添加'}</button></div>
    </form>
    {help && <CredentialHelp vendor={vendor} protocol={provider} onClose={() => setHelp(false)} />}
  </dialog>
}
