import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Sun, Moon, Inbox, Settings as SettingsIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { fetchAccounts, queryKeys } from '../api/queries'
import { providerBadge, providerColor, useMailStore } from '../store/mailStore'
import { confirmAction, ensureSuccess, errorMessage } from '../lib/actions'
import { IMPORT_PROVIDERS, importFormatHint } from '../lib/accounts'

export default function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { theme, setTheme } = useMailStore()
  const qc = useQueryClient()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts, enabled: open })
  const tagsQuery = useQuery({ queryKey: ['tags'], queryFn: async () => (await api.getTags()).tags || [], enabled: open })
  const tempQuery = useQuery({ queryKey: ['temp-emails'], queryFn: async () => (await api.getTempEmails()).emails || [], enabled: open })
  const accounts = accountsQuery.data || []
  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: async () => (await api.getProjects()).data?.projects || [], enabled: open })
  const [accountString, setAccountString] = useState('')
  const [oauthUrl, setOauthUrl] = useState('')
  const [redirectedUrl, setRedirectedUrl] = useState('')
  const [webdavUrl, setWebdavUrl] = useState('')
  const [webdavUser, setWebdavUser] = useState('')
  const [webdavPass, setWebdavPass] = useState('')
  const [projectKey, setProjectKey] = useState('')
  const [provider, setProvider] = useState('outlook')
  const [status, setStatus] = useState('')
  const [toolStatus, setToolStatus] = useState('')
  const [section, setSection] = useState<'accounts' | 'appearance' | 'general'>('accounts')
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: async () => (await api.getSettings()).settings || {}, enabled: open })
  const skinsQuery = useQuery({ queryKey: ['skins'], queryFn: async () => api.getSkins(), enabled: open && section === 'appearance' })
  const [timezone, setTimezone] = useState<string | null>(null)
  const [timeoutSeconds, setTimeoutSeconds] = useState<string | null>(null)
  const [reauthId, setReauthId] = useState('')
  const [oauthResult, setOauthResult] = useState<{ client_id?: string; refresh_token?: string } | null>(null)
  const [refreshProgress, setRefreshProgress] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const logsQuery = useQuery({ queryKey: ['forwarding-logs'], queryFn: async () => (await api.getForwardingLogs()).logs || [], enabled: open && section === 'general' })
  const sharesQuery = useQuery({ queryKey: ['shares'], queryFn: async () => (await api.getEmailShares()).shares || [], enabled: open && section === 'general' })
  const [groupName, setGroupName] = useState('')
  const [tagName, setTagName] = useState('')
  const [tempMessages, setTempMessages] = useState<Array<{ id?: string; subject?: string; from_address?: string }>>([])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  /** Run an action, surface errors (including HTTP 200 + success:false) in the status line. */
  async function run(label: string, fn: () => Promise<unknown>, ok: string, invalidate?: readonly unknown[]) {
    try {
      ensureSuccess(await fn(), `${label}失败`)
      setToolStatus(ok)
    } catch (err) {
      setToolStatus(errorMessage(err, `${label}失败`))
    } finally {
      if (invalidate) await qc.invalidateQueries({ queryKey: invalidate })
    }
  }

  const savedTimezone = settingsQuery.data?.app_timezone || ''
  const savedTimeout = settingsQuery.data?.mail_fetch_timeout_seconds || ''
  const timezoneValue = timezone ?? savedTimezone
  const timeoutValue = timeoutSeconds ?? savedTimeout

  async function addAccount(e: React.FormEvent) {
    e.preventDefault()
    setStatus('')
    try {
      const res = await api.addAccounts({
        account_string: accountString,
        provider,
        account_format: 'client_id_refresh_token',
      })
      if (res.success) {
        setStatus(res.message || '已添加')
        setAccountString('')
        await qc.invalidateQueries({ queryKey: queryKeys.accounts })
      } else {
        setStatus(res.error || '添加失败')
      }
    } catch (err: unknown) {
      setStatus(err && typeof err === 'object' && 'message' in err ? String((err as { message: string }).message) : '添加失败')
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 110, background: 'rgba(0,0,0,.46)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 18, backdropFilter: 'blur(5px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <section role="dialog" aria-modal="true" aria-labelledby="settings-title" style={{ width: 'min(760px, 100%)', height: 'min(680px, 88dvh)', display: 'flex', flexDirection: 'column', background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 15, boxShadow: 'var(--shadow)', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '13px 16px', borderBottom: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          <SettingsIcon size={16} />
          <strong id="settings-title" style={{ flex: 1, fontSize: 13 }}>设置</strong>
          <button type="button" title="关闭（Esc）" aria-label="关闭设置" onClick={onClose} style={{ height: 28, width: 28, display: 'grid', placeItems: 'center', border: 0, borderRadius: 7, background: 'transparent', color: 'var(--muted)' }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ display: 'flex', gap: 6, padding: '8px 16px', borderBottom: '1px solid var(--line)' }}>
          {([['accounts', '账户管理'], ['appearance', '外观'], ['general', '通用']] as const).map(([id, label]) => (
            <button key={id} type="button" onClick={() => { setSection(id); setToolStatus('') }} style={{ height: 32, padding: '0 12px', borderRadius: 8, border: '1px solid var(--line)', background: section === id ? 'var(--selected)' : 'transparent', fontWeight: 600 }}>
              {label}
            </button>
          ))}
        </div>
        <div style={{ minWidth: 0, flex: 1, overflow: 'auto', padding: '22px 24px' }}>
          {toolStatus && (
            <div role="status" aria-live="polite" style={{ position: 'sticky', top: -22, zIndex: 2, margin: '-6px 0 12px', padding: '8px 12px', borderRadius: 9, fontSize: 12, border: '1px solid var(--line)', background: 'var(--surface-2)', color: /失败|错误|无效/.test(toolStatus) ? 'var(--red)' : 'var(--text)', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ flex: 1 }}>{toolStatus}</span>
              <button type="button" aria-label="关闭提示" title="关闭提示" onClick={() => setToolStatus('')} style={{ border: 0, background: 'transparent', color: 'var(--muted)' }}><X size={13} /></button>
            </div>
          )}
          {section === 'accounts' && <>
          <div style={{ fontSize: 18, fontWeight: 720, margin: '0 0 6px' }}>账户管理</div>
          <p style={{ margin: '0 0 12px', color: 'var(--muted)', fontSize: 12 }}>添加账户走现有导入接口。OAuth 完整向导仍可在 /legacy 完成。</p>
          <form onSubmit={addAccount} style={{ border: '1px solid var(--line)', borderRadius: 11, padding: 12, marginBottom: 14 }}>
            <label className="field-label" htmlFor="import-provider">账户类型</label>
            <select id="import-provider" value={provider} onChange={(e) => setProvider(e.target.value)} style={{ height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', marginBottom: 8 }}>
              {IMPORT_PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
            <label className="field-label" htmlFor="import-lines">账号（每行一个）</label>
            <textarea id="import-lines" aria-describedby="import-hint" value={accountString} onChange={(e) => setAccountString(e.target.value)} placeholder={importFormatHint(provider).placeholder} style={{ width: '100%', minHeight: 72, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: 8 }} />
            <div id="import-hint" className="field-hint">{importFormatHint(provider).help}</div>
            <button type="submit" style={{ marginTop: 8, height: 32, padding: '0 12px', border: 0, borderRadius: 8, background: 'var(--blue)', color: '#fff' }}>添加账户</button>
            {status && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>{status}</div>}
          </form>
          <div style={{ border: '1px solid var(--line)', borderRadius: 11, overflow: 'hidden' }}>
            {accountsQuery.isLoading && <div style={{ padding: 16, color: 'var(--muted)' }}>加载中…</div>}
            {accounts.length === 0 && !accountsQuery.isLoading && <div style={{ padding: 16, color: 'var(--muted)' }}>暂无账户</div>}
            {accounts.map((a) => (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 11px', minHeight: 51, borderBottom: '1px solid var(--line)' }}>
                <span style={{ width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: 8, color: '#fff', fontSize: 10, fontWeight: 800, background: a.group_color || providerColor(a.provider, a.account_type) }}>
                  {providerBadge(a.provider, a.account_type)}
                </span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <strong style={{ fontSize: 12 }}>{a.email}</strong>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>{a.provider} · {a.group_name || '未分组'} · {a.status}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>重新授权</div>
            <select value={reauthId} onChange={(e) => setReauthId(e.target.value)} style={{ height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }}>
              <option value="">选择账户</option>
              {accounts.map((a) => <option key={a.id} value={String(a.id)}>{a.email}</option>)}
            </select>
            <button type="button" onClick={async () => {
              const id = Number(reauthId)
              if (!id || !redirectedUrl) { setToolStatus('选择账户并在下方粘贴授权回调 URL'); return }
              await run('重新授权', () => api.reauthorizeAccount(id, redirectedUrl), '已重新授权', queryKeys.accounts)
            }} style={{ marginLeft: 8, height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>提交重新授权</button>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
          <div style={{ marginTop: 12, fontSize: 14, fontWeight: 700 }}>分组与标签</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input value={groupName} onChange={(e) => setGroupName(e.target.value)} placeholder="新分组名称" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <button type="button" onClick={async () => {
              if (!groupName.trim()) { setToolStatus('请输入分组名称'); return }
              await run('创建分组', () => api.createGroup({ name: groupName.trim() }), '分组已创建', queryKeys.groups)
              setGroupName('')
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>创建分组</button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input value={tagName} onChange={(e) => setTagName(e.target.value)} placeholder="新标签" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <button type="button" onClick={async () => {
              if (!tagName.trim()) { setToolStatus('请输入标签名称'); return }
              await run('创建标签', () => api.createTag(tagName.trim()), '标签已创建', ['tags'])
              setTagName('')
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>创建标签</button>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
            标签 {(tagsQuery.data || []).length} 个 · 临时邮箱 {(tempQuery.data || []).length} 个
            {(tagsQuery.data || []).map((t) => (
              <button key={t.id} type="button" onClick={async () => {
                if (!confirmAction(`删除标签「${t.name}」？已打在账号上的该标签也会移除。`)) return
                await run('删除标签', () => api.deleteTag(t.id), '标签已删除', ['tags'])
              }} style={{ marginLeft: 6, border: 0, background: 'transparent', color: 'var(--danger)' }}>{t.name} ×</button>
            ))}
          </div>
          </div>
          <div style={{ marginTop: 22, fontSize: 16, fontWeight: 700 }}>OAuth / 转发 / 项目</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <button type="button" onClick={async () => {
              try {
                const res = ensureSuccess(await api.getOauthUrl(), '获取授权链接失败')
                setOauthUrl(res.auth_url || '')
                if (res.auth_url) window.open(res.auth_url, '_blank', 'noopener')
              } catch (err) {
                setToolStatus(errorMessage(err, '获取授权链接失败'))
              }
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>打开 Outlook 授权</button>
            <button type="button" onClick={async () => {
              const ids = accounts.map((a) => a.id)
              if (!ids.length) { setToolStatus('暂无账户'); return }
              if (!confirmAction(`对全部 ${ids.length} 个账户开启邮件转发？`)) return
              await run('开启转发', () => api.setForwarding(ids, true), `已对 ${ids.length} 个账户开启转发`, queryKeys.accounts)
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>全部开启转发</button>
            <button type="button" onClick={async () => {
              const ids = accounts.map((a) => a.id)
              if (!ids.length) { setToolStatus('暂无账户'); return }
              if (!confirmAction(`对全部 ${ids.length} 个账户关闭邮件转发？`)) return
              await run('关闭转发', () => api.setForwarding(ids, false), `已对 ${ids.length} 个账户关闭转发`, queryKeys.accounts)
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>全部关闭转发</button>
          </div>
          {oauthUrl && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)', wordBreak: 'break-all' }}>{oauthUrl}</div>}
          <input value={redirectedUrl} onChange={(e) => setRedirectedUrl(e.target.value)} placeholder="粘贴授权回调 URL" style={{ width: '100%', marginTop: 8, height: 34, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
          <button type="button" onClick={async () => {
            setOauthResult(null)
            try {
              const res = ensureSuccess(await api.exchangeOauth(redirectedUrl), '换取失败')
              setOauthResult({ client_id: res.client_id, refresh_token: res.refresh_token })
              setToolStatus('已换取 Refresh Token，请复制保存或用于导入账户')
            } catch (err) {
              setToolStatus(errorMessage(err, '换取失败'))
            }
          }} style={{ marginTop: 8, height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>换取 Refresh Token</button>
          {oauthResult?.refresh_token && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Client ID：{oauthResult.client_id || '（默认应用）'}</div>
              <textarea readOnly value={oauthResult.refresh_token} onFocus={(e) => e.currentTarget.select()} aria-label="Refresh Token" style={{ width: '100%', minHeight: 60, marginTop: 4, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: 8, fontSize: 11 }} />
            </div>
          )}
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
            项目 {(projectsQuery.data || []).length} 个
            {(projectsQuery.data || []).slice(0, 5).map((p) => ` · ${p.name || p.project_key || '未命名'}`)}
          </div>
          <div style={{ marginTop: 18, fontSize: 15, fontWeight: 700 }}>临时邮箱</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button type="button" onClick={async () => {
              try {
                const res = ensureSuccess(await api.generateTempEmail({ provider: 'gptmail' }), '生成失败')
                setToolStatus(res.email ? `已生成 ${res.email}` : (res.message || '已生成'))
              } catch (err) {
                setToolStatus(errorMessage(err, '生成失败'))
              }
              await qc.invalidateQueries({ queryKey: ['temp-emails'] })
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>生成 GPTMail</button>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
            {(tempQuery.data || []).slice(0, 8).map((item) => {
              const address = item.email || item.address
              if (!address) return null
              return (
                <div key={address} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 0' }}>
                  <span>{address}</span>
                  <button type="button" onClick={async () => {
                    if (!confirmAction(`删除临时邮箱 ${address}？其邮件也会一并删除。`)) return
                    await run('删除临时邮箱', () => api.deleteTempEmail(address), `已删除 ${address}`, ['temp-emails'])
                  }} style={{ border: 0, background: 'transparent', color: 'var(--danger)' }}>删除</button>
                </div>
              )
            })}
            {(tempQuery.data || []).length === 0 && '暂无临时邮箱'}
          </div>
          <div style={{ marginTop: 18, fontSize: 15, fontWeight: 700 }}>项目</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input value={projectKey} onChange={(e) => setProjectKey(e.target.value)} placeholder="project key" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <button type="button" onClick={async () => {
              const key = projectKey.trim()
              if (!key) { setToolStatus('请输入 project key'); return }
              await run('启动项目', () => api.startProject({ project_key: key, name: key }), '项目已启动', ['projects'])
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>启动项目</button>
            <button type="button" onClick={async () => {
              const key = projectKey.trim()
              if (!key) { setToolStatus('请输入 project key'); return }
              if (!confirmAction(`归档项目 ${key}？`)) return
              await run('归档项目', () => api.archiveProject(key), '项目已归档', ['projects'])
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>归档项目</button>
            <button type="button" onClick={async () => {
              const key = projectKey.trim()
              if (!key) { setToolStatus('请输入 project key'); return }
              if (!confirmAction(`永久删除项目 ${key}？此操作不可撤销。`)) return
              await run('删除项目', () => api.deleteProject(key), '项目已删除', ['projects'])
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'var(--danger)' }}>删除项目</button>
          </div>
          <div style={{ marginTop: 18, fontSize: 15, fontWeight: 700 }}>WebDAV 备份</div>
          <input value={webdavUrl} onChange={(e) => setWebdavUrl(e.target.value)} placeholder="https://dav.example.com/backup/" style={{ width: '100%', marginTop: 8, height: 34, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input value={webdavUser} onChange={(e) => setWebdavUser(e.target.value)} placeholder="用户名" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <input value={webdavPass} onChange={(e) => setWebdavPass(e.target.value)} type="password" placeholder="密码" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button type="button" onClick={async () => {
              await run('WebDAV 测试', () => api.testWebdav({ url: webdavUrl, username: webdavUser, password: webdavPass }), 'WebDAV 测试成功')
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>测试备份</button>
            <button type="button" onClick={async () => {
              await run('WebDAV 备份', () => api.uploadWebdav({ url: webdavUrl, username: webdavUser, password: webdavPass }), '已上传备份')
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>立即备份</button>
          </div>
          </>}
          {section === 'appearance' && <>
          <div style={{ marginTop: 22, fontSize: 18, fontWeight: 720 }}>外观</div>
          <div style={{ marginTop: 16, fontSize: 14, fontWeight: 700 }}>新界面主题</div>
          <div style={{ marginTop: 6, fontSize: 12, color: 'var(--muted)' }}>当前：{theme === 'dark' ? '深夜' : '亮色'}</div>
          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button type="button" aria-pressed={theme === 'light'} onClick={() => setTheme('light')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 12, borderRadius: 11, border: `1px solid ${theme === 'light' ? 'var(--blue)' : 'var(--line)'}`, background: 'var(--surface)' }}>
              <Sun size={18} /> 亮色
            </button>
            <button type="button" aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 12, borderRadius: 11, border: `1px solid ${theme === 'dark' ? 'var(--blue)' : 'var(--line)'}`, background: 'var(--surface)' }}>
              <Moon size={18} /> 深夜
            </button>
          </div>
          <div style={{ marginTop: 22, fontSize: 14, fontWeight: 700 }}>旧版界面皮肤</div>
          <div style={{ marginTop: 6, fontSize: 12, color: 'var(--muted)' }}>
            仅作用于 /legacy 旧版界面，不影响当前界面。旧版当前皮肤：{skinsQuery.data?.active_skin_id || 'classic'}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            {(skinsQuery.data?.skins || []).map((skin) => (
              <button key={skin.id} type="button" onClick={async () => {
                if (!skin.id) return
                await run('启用皮肤', () => api.activateSkin(skin.id!), '皮肤已启用', ['skins'])
              }} style={{ height: 30, padding: '0 8px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>{skin.name || skin.id}</button>
            ))}
          </div>
          </>}
          {section === 'general' && (
            <div>
              <div style={{ fontSize: 18, fontWeight: 720, margin: '0 0 10px' }}>通用</div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>转发记录 {(logsQuery.data || []).length} 条</div>
              {(logsQuery.data || []).slice(0, 6).map((log) => {
                const row = log as { id?: number; account_email?: string; status?: string; created_at?: string }
                return <div key={row.id} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--line)' }}>{row.account_email} · {row.status} · {row.created_at}</div>
              })}
              <div style={{ marginTop: 16, fontSize: 14, fontWeight: 700 }}>令牌刷新与邮件分享</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button type="button" onClick={async () => {
                  if (!confirmAction('刷新全部账户的令牌？账户多时会持续一段时间。')) return
                  setRefreshProgress('开始刷新…')
                  try {
                    const summary = await api.refreshAllStream((evt) => {
                      if (evt.type === 'progress') setRefreshProgress(`进度 ${evt.current ?? 0}/${evt.total ?? 0} · 成功 ${evt.success_count ?? 0} · 失败 ${evt.failed_count ?? 0}`)
                    })
                    setRefreshProgress('')
                    setToolStatus(summary.type === 'error'
                      ? (summary.message || '刷新失败')
                      : `刷新完成：成功 ${summary.success_count ?? 0}，失败 ${summary.failed_count ?? 0}`)
                  } catch (err) {
                    setRefreshProgress('')
                    setToolStatus(errorMessage(err, '刷新失败'))
                  }
                  await qc.invalidateQueries({ queryKey: queryKeys.accounts })
                }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>刷新全部令牌</button>
                {refreshProgress && <span style={{ alignSelf: 'center', fontSize: 12, color: 'var(--muted)' }}>{refreshProgress}</span>}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
                分享 {(sharesQuery.data || []).length} 条
                {(sharesQuery.data || []).slice(0, 5).map((s) => ` · ${s.email || s.id}`)}
              </div>
              <div style={{ marginTop: 16, fontSize: 14, fontWeight: 700 }}>时区与拉取超时</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <label className="field-label" htmlFor="settings-timezone" style={{ flex: 1, margin: 0 }}>时区（IANA 名称）</label>
                <label className="field-label" htmlFor="settings-timeout" style={{ width: 90, margin: 0 }}>拉取超时（秒）</label>
                <span style={{ width: 52 }} />
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                <input id="settings-timezone" value={timezoneValue} onChange={(e) => setTimezone(e.target.value)} placeholder="Asia/Shanghai" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
                <input id="settings-timeout" inputMode="numeric" value={timeoutValue} onChange={(e) => setTimeoutSeconds(e.target.value)} placeholder="30" style={{ width: 90, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
                <button type="button" onClick={async () => {
                  // Only send fields the user actually changed, so untouched settings keep their stored values.
                  const payload: Record<string, string> = {}
                  if (timezone !== null && timezone.trim() && timezone.trim() !== savedTimezone) payload.app_timezone = timezone.trim()
                  if (timeoutSeconds !== null && timeoutSeconds.trim() && timeoutSeconds.trim() !== savedTimeout) payload.mail_fetch_timeout_seconds = timeoutSeconds.trim()
                  if (!Object.keys(payload).length) { setToolStatus('没有需要保存的改动'); return }
                  await run('保存设置', () => api.updateSettings(payload), `设置已保存${payload.app_timezone ? `：时区 ${payload.app_timezone}` : ''}${payload.mail_fetch_timeout_seconds ? `，超时 ${payload.mail_fetch_timeout_seconds} 秒` : ''}`, ['settings'])
                  setTimezone(null)
                  setTimeoutSeconds(null)
                }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>保存</button>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <input value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} type="password" placeholder="当前密码" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
                <input value={newPassword} onChange={(e) => setNewPassword(e.target.value)} type="password" placeholder="新密码至少 8 位" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
                <button type="button" onClick={async () => {
                  if (!currentPassword || newPassword.length < 8) { setToolStatus('请输入当前密码，新密码至少 8 位'); return }
                  await run('修改密码', () => api.updateSettings({ current_login_password: currentPassword, login_password: newPassword }), '密码已更新')
                  setCurrentPassword('')
                  setNewPassword('')
                }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>改密</button>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                {(tempQuery.data || []).slice(0, 4).map((item) => {
                  const address = item.email || item.address
                  if (!address) return null
                  return (
                    <button key={address} type="button" onClick={async () => {
                      try {
                        const res = ensureSuccess(await api.getTempEmailMessages(address), '读取失败')
                        setTempMessages(res.messages || [])
                        setToolStatus(`${address} 有 ${(res.messages || []).length} 封`)
                      } catch (err) {
                        setTempMessages([])
                        setToolStatus(errorMessage(err, '读取失败'))
                      }
                    }} style={{ height: 30, padding: '0 8px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>{address}</button>
                  )
                })}
              </div>
              {tempMessages.slice(0, 5).map((m, i) => <div key={m.id || i} style={{ fontSize: 12, marginTop: 6 }}>{m.from_address} · {m.subject}</div>)}
              <div style={{ marginTop: 18, color: 'var(--muted)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Inbox size={14} /> 旧版完整管理界面仍可从 /legacy 进入。规范见仓库根目录 DESIGN.md。
              </div>
              <button type="button" onClick={() => api.logout()} style={{ marginTop: 16, height: 32, padding: '0 12px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'var(--danger)' }}>退出登录</button>
            </div>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '12px 16px', borderTop: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          <button onClick={onClose} style={{ height: 35, padding: '0 15px', border: 0, borderRadius: 9, background: 'var(--blue)', color: '#fff', fontWeight: 650 }}>完成</button>
        </div>
      </section>
    </div>
  )
}
