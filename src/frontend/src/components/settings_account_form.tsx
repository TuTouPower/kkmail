import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api, type AccountSummary } from '../api/client'
import type { GroupItem } from '../api/queries'
import { errorMessage } from '../lib/actions'

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
  const [credentialJson, setCredentialJson] = useState('')
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
      if (credentialJson.trim()) {
        try {
          const parsed: unknown = JSON.parse(credentialJson)
          if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') { setStatus('凭据必须是 JSON 对象'); return }
          credentials = parsed as Record<string, unknown>
        } catch { setStatus('credentials JSON 无效'); return }
      }
      if (provider === 'imap' && password) credentials = { ...credentials, password }
      const parsedPort = Number(port)
      if (provider === 'imap' && (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65535)) { setStatus('端口必须为 1–65535 的整数'); return }
      busyRef.current = true
      setBusy(true)
      setStatus('')
      let saved = false
      try {
        if (account) {
          await api.updateAccount(account.id, {
            ...(provider === 'imap' ? { config: { imap_host: host.trim(), imap_port: parsedPort, use_ssl: ssl } } : {}),
            ...(groupId !== (account.group_id || '') && groupsAvailable ? (groupId ? { group_id: groupId } : { clear_group: true }) : {}),
            ...(Object.keys(credentials).length ? { credentials } : {}),
          })
        } else {
          await api.addAccount({
            email: email.trim(), provider,
            ...(groupId && groupsAvailable ? { group_id: groupId } : {}),
            credentials,
            ...(provider === 'imap' ? { config: { imap_host: host.trim(), imap_port: parsedPort, use_ssl: ssl } } : {}),
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
        <label className="settings-field" htmlFor="account-email"><span>邮箱地址</span><input ref={emailRef} id="account-email" name="email" type="email" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} readOnly={!!account} required placeholder="name@example.com" maxLength={320} /></label>
        <div className="settings-fields"><label className="settings-field" htmlFor="account-provider"><span>连接协议</span><select id="account-provider" name="provider" value={provider} disabled={!!account} onChange={event => { setProvider(event.target.value as typeof provider); setPassword(''); setCredentialJson('') }}><option value="imap">IMAP</option><option value="gmail">Gmail API</option><option value="graph">Microsoft Graph</option></select></label><label className="settings-field" htmlFor="account-group"><span>所属分组</span><select id="account-group" value={groupId} onChange={event => setGroupId(event.target.value)} disabled={!groupsAvailable}><option value="">不加入分组</option>{groups.map(group => <option value={group.id} key={group.id}>{group.name}</option>)}</select></label></div>
        {provider === 'imap' ? <>
          {/@(outlook|hotmail|live|msn)\.com$/i.test(email.trim()) && <p className="settings-notice">Outlook / Hotmail 已停用普通密码认证，建议使用 Microsoft Graph。</p>}
          <label className="settings-field" htmlFor="account-imap-host"><span>IMAP 服务器</span><input id="account-imap-host" name="imap_host" value={host} onChange={event => setHost(event.target.value)} required placeholder="imap.example.com" /></label>
          <div className="settings-fields"><label className="settings-field" htmlFor="account-imap-port"><span>端口</span><input id="account-imap-port" name="imap_port" type="number" min={1} max={65535} required value={port} onChange={event => setPort(event.target.value)} /></label><label className="settings-checkbox"><input id="account-imap-ssl" name="use_ssl" type="checkbox" checked={ssl} onChange={event => { setSsl(event.target.checked); if (port === '993' && !event.target.checked) setPort('143'); else if (port === '143' && event.target.checked) setPort('993') }} />SSL / TLS</label></div>
          <label className="settings-field" htmlFor="account-password"><span>密码或授权码</span><input id="account-password" name="mailbox-password" type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} placeholder={account ? '留空保持已保存密码不变' : '邮箱服务商提供的密码或授权码'} /></label>
        </> : <p className="settings-notice">{account ? '凭据不会回显；需要更换时，请填写完整的 OAuth 凭据 JSON。' : '使用已有 OAuth 凭据连接，在下方填写凭据 JSON。'}</p>}
        <details className="settings-advanced" open={provider !== 'imap' || undefined}><summary>高级凭据配置</summary><label className="settings-field" htmlFor="account-credentials"><span>凭据 JSON</span><textarea id="account-credentials" name="credentials" autoComplete="off" spellCheck={false} value={credentialJson} onChange={event => setCredentialJson(event.target.value)} placeholder={account ? '留空保持已保存凭据不变' : '填写 refresh_token、client_id 等凭据字段'} /><small>仅接受 JSON 对象。IMAP 密码输入框非空时优先使用该密码。</small></label></details>
      </fieldset>
      {status && <div className="settings-feedback is-error" role="alert">{status}</div>}
      <div className="settings-dialog-actions"><button type="button" className="settings-button" onClick={onClose} disabled={busy && !status}>取消</button><button type="submit" className="settings-button is-primary" disabled={busy}>{busy && !status ? '正在保存…' : account ? '保存修改' : '添加'}</button></div>
    </form>
  </dialog>
}
