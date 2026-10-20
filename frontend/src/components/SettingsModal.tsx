import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Sun, Moon, Inbox, Settings as SettingsIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { fetchAccounts, fetchGroups, queryKeys } from '../api/queries'
import { providerBadge, providerColor, useMailStore } from '../store/mailStore'
import { confirmAction, errorMessage } from '../lib/actions'

/** Settings page — mail-core only (accounts / groups / appearance / password). */
export default function SettingsPage() {
  const { theme, setTheme, closeSettings } = useMailStore()
  const onClose = closeSettings
  const qc = useQueryClient()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const groupsQuery = useQuery({ queryKey: queryKeys.groups, queryFn: fetchGroups })
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: async () => (await api.getSettings()).settings })
  const accounts = accountsQuery.data || []
  const groups = groupsQuery.data || []
  const [section, setSection] = useState<'accounts' | 'appearance' | 'general'>('accounts')
  const [status, setStatus] = useState('')
  const [email, setEmail] = useState('')
  const [provider, setProvider] = useState<'gmail' | 'imap' | 'graph' | 'memory' | 'stub'>('imap')
  const [credJson, setCredJson] = useState('')
  const [imapHost, setImapHost] = useState('')
  const [imapPort, setImapPort] = useState('993')
  const [imapUseSsl, setImapUseSsl] = useState(true)
  const [groupName, setGroupName] = useState('')
  const [timezone, setTimezone] = useState<string | null>(null)
  const [timeoutSeconds, setTimeoutSeconds] = useState<string | null>(null)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const savedTimezone = settingsQuery.data?.app_timezone || ''
  const savedTimeout = settingsQuery.data?.mail_fetch_timeout_seconds || ''

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function run(label: string, fn: () => Promise<unknown>, okMsg: string, invalidate?: unknown) {
    setStatus(`${label}…`)
    try {
      await fn()
      setStatus(okMsg)
      if (invalidate) await qc.invalidateQueries({ queryKey: invalidate as readonly unknown[] })
    } catch (err) {
      setStatus(errorMessage(err, `${label}失败`))
    }
  }

  return (
    <div className="settings-page" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--surface)', color: 'var(--text)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--line)' }}>
        <SettingsIcon size={18} />
        <div style={{ fontWeight: 700, flex: 1 }}>设置</div>
        <button type="button" onClick={onClose} title="关闭" aria-label="关闭" style={{ border: 0, background: 'transparent', color: 'var(--muted)' }}><X size={18} /></button>
      </div>
      <div style={{ display: 'flex', gap: 8, padding: '10px 16px', borderBottom: '1px solid var(--line)' }}>
        {([
          ['accounts', '账户', Inbox],
          ['appearance', '外观', theme === 'light' ? Sun : Moon],
          ['general', '通用', SettingsIcon],
        ] as const).map(([id, label, Icon]) => (
          <button key={id} type="button" onClick={() => setSection(id)} style={{
            height: 32, padding: '0 12px', borderRadius: 8, border: '1px solid var(--line)',
            background: section === id ? 'var(--blue)' : 'var(--surface-2)',
            color: section === id ? '#fff' : 'var(--text)', display: 'inline-flex', alignItems: 'center', gap: 6,
          }}><Icon size={14} />{label}</button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {section === 'accounts' && (
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>账户（{accounts.length}）</div>
            {accountsQuery.isError && (
              <div role="alert" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 10 }}>
                加载账户失败：{errorMessage(accountsQuery.error, '未知错误')}
              </div>
            )}
            {groupsQuery.isError && (
              <div role="alert" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 10 }}>
                加载分组失败：{errorMessage(groupsQuery.error, '未知错误')}
              </div>
            )}
            {accounts.map((a) => (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderBottom: '1px solid var(--line)' }}>
                <span className="account-dot" style={{ background: a.group_color || providerColor(a.provider, a.account_type) }}>{providerBadge(a.provider, a.account_type)}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 650 }}>{a.email}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>{a.provider} · {a.sync_status || a.status}{a.group_name ? ` · ${a.group_name}` : ''}</div>
                </div>
                <button type="button" onClick={() => run('同步', () => api.syncAccount(a.id), '已排队同步', queryKeys.accounts)} style={{ height: 28, padding: '0 8px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>同步</button>
                <button type="button" onClick={async () => {
                  if (!confirmAction(`删除账户 ${a.email}？`)) return
                  await run('删除账户', () => api.deleteAccount(a.id), '已删除', queryKeys.accounts)
                }} style={{ height: 28, padding: '0 8px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'var(--red)' }}>删除</button>
              </div>
            ))}
            <div style={{ marginTop: 18, fontWeight: 700 }}>添加账户</div>
            <p style={{ fontSize: 12, color: 'var(--muted)' }}>credentials 为 JSON（如 refresh_token / client_id），写入凭证库，接口不会回显。</p>
            <input id="account-email" name="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email" style={{ width: '100%', height: 34, marginTop: 8, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <select id="account-provider" name="provider" value={provider} onChange={(e) => setProvider(e.target.value as 'gmail' | 'imap' | 'graph' | 'memory' | 'stub')} style={{ width: '100%', height: 34, marginTop: 8, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }}>
              <option value="imap">imap</option>
              <option value="gmail">gmail</option>
              <option value="graph">graph</option>
            </select>
            {provider === 'imap' && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  id="account-imap-host"
                  name="imap_host"
                  value={imapHost}
                  onChange={(e) => setImapHost(e.target.value)}
                  placeholder="IMAP 服务器 (imap_host, 必填)"
                  style={{ width: '100%', height: 34, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }}
                  required
                />
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input
                    id="account-imap-port"
                    name="imap_port"
                    type="number"
                    value={imapPort}
                    onChange={(e) => setImapPort(e.target.value)}
                    placeholder="端口 (默认 993)"
                    style={{ width: 120, height: 34, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }}
                  />
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                    <input
                      id="account-imap-ssl"
                      name="use_ssl"
                      type="checkbox"
                      checked={imapUseSsl}
                      onChange={(e) => {
                        const next = e.target.checked
                        setImapUseSsl(next)
                        if (imapPort === '993' && !next) setImapPort('143')
                        else if (imapPort === '143' && next) setImapPort('993')
                      }}
                    />
                    SSL / TLS
                  </label>
                </div>
              </div>
            )}
            <textarea id="account-credentials" name="credentials" value={credJson} onChange={(e) => setCredJson(e.target.value)} placeholder='{"refresh_token":"...","client_id":"..."} 或 IMAP password JSON' style={{ width: '100%', minHeight: 80, marginTop: 8, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: 8, fontSize: 12 }} />
            <button type="button" onClick={async () => {
              if (!email.trim()) {
                setStatus('请输入邮箱地址')
                return
              }
              let credentials: Record<string, unknown> | undefined
              if (credJson.trim()) {
                try { credentials = JSON.parse(credJson) } catch { setStatus('credentials JSON 无效'); return }
              }
              let config: Record<string, unknown> | undefined
              if (provider === 'imap') {
                if (!imapHost.trim()) {
                  setStatus('IMAP 服务器（imap_host）为必填项')
                  return
                }
                config = {
                  imap_host: imapHost.trim(),
                  imap_port: Number.parseInt(imapPort, 10) || (imapUseSsl ? 993 : 143),
                  use_ssl: imapUseSsl,
                }
              }
              setStatus('添加账户…')
              try {
                await api.addAccount({ email: email.trim(), provider, credentials, config })
                setStatus('账户已添加')
                setEmail(''); setCredJson(''); setImapHost(''); setImapPort('993'); setImapUseSsl(true)
                await qc.invalidateQueries({ queryKey: queryKeys.accounts })
              } catch (err) {
                setStatus(errorMessage(err, '添加账户失败'))
              }
            }} style={{ marginTop: 8, height: 34, padding: '0 12px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>添加</button>

            <div style={{ marginTop: 22, fontWeight: 700 }}>分组</div>
            {(groups || []).map((g) => (
              <div key={g.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0' }}>
                <span style={{ flex: 1 }}>{g.name}（{g.account_count || 0}）</span>
                <button type="button" onClick={async () => {
                  if (!confirmAction(`删除分组 ${g.name}？`)) return
                  await run('删除分组', () => api.deleteGroup(g.id), '已删除', queryKeys.groups)
                }} style={{ height: 28, padding: '0 8px', borderRadius: 8, border: '1px solid var(--line)' }}>删除</button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <input value={groupName} onChange={(e) => setGroupName(e.target.value)} placeholder="新分组名" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
              <button type="button" onClick={async () => {
                await run('创建分组', () => api.createGroup({ name: groupName.trim() }), '分组已创建', queryKeys.groups)
                setGroupName('')
              }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>创建</button>
            </div>
            <button type="button" onClick={() => run('全量同步', async () => setStatus(`已排队 ${(await api.syncAll()).count} 个同步任务`), '同步任务已排队', queryKeys.accounts)} style={{ marginTop: 16, height: 34, padding: '0 12px', borderRadius: 8, border: '1px solid var(--line)' }}>同步全部账户</button>
          </div>
        )}

        {section === 'appearance' && (
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>外观</div>
            <div style={{ display: 'flex', gap: 8 }}>
              {(['system', 'light', 'dark'] as const).map((t) => (
                <button key={t} type="button" onClick={() => setTheme(t)} style={{
                  height: 34, padding: '0 12px', borderRadius: 8, border: '1px solid var(--line)',
                  background: theme === t ? 'var(--blue)' : 'var(--surface-2)', color: theme === t ? '#fff' : 'var(--text)',
                }}>{t}</button>
              ))}
            </div>
          </div>
        )}

        {section === 'general' && (
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>通用</div>
            {settingsQuery.isError && (
              <div role="alert" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 10 }}>
                加载设置失败：{errorMessage(settingsQuery.error, '未知错误')}
              </div>
            )}
            <label style={{ fontSize: 12, color: 'var(--muted)' }}>时区</label>
            <input value={timezone ?? savedTimezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Asia/Shanghai" style={{ width: '100%', height: 34, marginTop: 4, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginTop: 10 }}>拉信超时（秒）</label>
            <input value={timeoutSeconds ?? savedTimeout} onChange={(e) => setTimeoutSeconds(e.target.value)} placeholder="120" style={{ width: '100%', height: 34, marginTop: 4, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <button type="button" onClick={async () => {
              const payload: Record<string, string> = {}
              if (timezone !== null && timezone.trim() && timezone.trim() !== savedTimezone) payload.app_timezone = timezone.trim()
              if (timeoutSeconds !== null && timeoutSeconds.trim() && timeoutSeconds.trim() !== savedTimeout) payload.mail_fetch_timeout_seconds = timeoutSeconds.trim()
              if (!Object.keys(payload).length) { setStatus('没有改动'); return }
              await run('保存设置', () => api.updateSettings(payload), '设置已保存', ['settings'])
            }} style={{ marginTop: 10, height: 34, padding: '0 12px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>保存</button>

            <div style={{ marginTop: 22, fontWeight: 700 }}>修改登录密码</div>
            <form onSubmit={(e) => {
              e.preventDefault()
              run('修改密码', () => api.changePassword(currentPassword, newPassword), '密码已更新')
            }}>
              <input
                id="current-password"
                name="current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="当前密码"
                style={{ width: '100%', height: 34, marginTop: 8, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }}
              />
              <input
                id="new-password"
                name="new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="新密码（≥8）"
                style={{ width: '100%', height: 34, marginTop: 8, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }}
              />
              <button type="submit" style={{ marginTop: 10, height: 34, padding: '0 12px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>更新密码</button>
            </form>
          </div>
        )}
        {status && <div style={{ marginTop: 16, fontSize: 12, color: 'var(--muted)' }}>{status}</div>}
      </div>
    </div>
  )
}
