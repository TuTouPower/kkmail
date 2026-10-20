import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Sun, Moon, Inbox, Settings as SettingsIcon } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { fetchAccounts, queryKeys } from '../api/queries'
import { providerBadge, providerColor, useMailStore } from '../store/mailStore'

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
  const [toolStatus, setToolStatus] = useState('')
  const [provider, setProvider] = useState('outlook')
  const [status, setStatus] = useState('')
  const [section, setSection] = useState<'accounts' | 'appearance' | 'general'>('accounts')

  if (!open) return null

  async function addAccount(e: React.FormEvent) {
    e.preventDefault()
    setStatus('')
    try {
      const res = await api.addAccounts({
        account_string: accountString,
        provider,
        account_format: provider === 'imap' || provider === 'gmail' || provider === '163' ? 'imap' : 'client_id_refresh_token',
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
      <section style={{ width: 'min(760px, 100%)', height: 'min(680px, 88dvh)', display: 'flex', flexDirection: 'column', background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 15, boxShadow: 'var(--shadow)', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '13px 16px', borderBottom: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          <SettingsIcon size={16} />
          <strong style={{ flex: 1, fontSize: 13 }}>设置</strong>
          <button onClick={onClose} style={{ height: 28, width: 28, display: 'grid', placeItems: 'center', border: 0, borderRadius: 7, background: 'transparent', color: 'var(--muted)' }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ display: 'flex', gap: 6, padding: '8px 16px', borderBottom: '1px solid var(--line)' }}>
          {([['accounts', '账户管理'], ['appearance', '外观'], ['general', '通用']] as const).map(([id, label]) => (
            <button key={id} type="button" onClick={() => setSection(id)} style={{ height: 32, padding: '0 12px', borderRadius: 8, border: '1px solid var(--line)', background: section === id ? 'var(--selected)' : 'transparent', fontWeight: 600 }}>
              {label}
            </button>
          ))}
        </div>
        <div style={{ minWidth: 0, flex: 1, overflow: 'auto', padding: '22px 24px' }}>
          {section === 'accounts' && <>
          <div style={{ fontSize: 18, fontWeight: 720, margin: '0 0 6px' }}>账户管理</div>
          <p style={{ margin: '0 0 12px', color: 'var(--muted)', fontSize: 12 }}>添加账户走现有导入接口。OAuth 完整向导仍可在 /legacy 完成。</p>
          <form onSubmit={addAccount} style={{ border: '1px solid var(--line)', borderRadius: 11, padding: 12, marginBottom: 14 }}>
            <select value={provider} onChange={(e) => setProvider(e.target.value)} style={{ height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', marginBottom: 8 }}>
              <option value="outlook">Outlook / Graph</option>
              <option value="gmail">Gmail IMAP</option>
              <option value="163">网易 163</option>
              <option value="imap">自定义 IMAP</option>
            </select>
            <textarea value={accountString} onChange={(e) => setAccountString(e.target.value)} placeholder="每行一个账号，格式与旧版导入一致" style={{ width: '100%', minHeight: 72, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: 8 }} />
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
          <div style={{ marginTop: 22, fontSize: 16, fontWeight: 700 }}>标签与临时邮箱</div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
            标签 {(tagsQuery.data || []).length} 个 · 临时邮箱 {(tempQuery.data || []).length} 个
          </div>
          <div style={{ marginTop: 22, fontSize: 16, fontWeight: 700 }}>OAuth / 转发 / 项目</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <button type="button" onClick={async () => {
              const res = await api.getOauthUrl()
              setOauthUrl(res.auth_url || '')
              if (res.auth_url) window.open(res.auth_url, '_blank', 'noopener')
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>打开 Outlook 授权</button>
            <button type="button" onClick={async () => {
              const ids = accounts.map((a) => a.id)
              const res = await api.setForwarding(ids, true)
              setToolStatus(res.message || res.error || '已请求开启转发')
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>全部开启转发</button>
          </div>
          {oauthUrl && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)', wordBreak: 'break-all' }}>{oauthUrl}</div>}
          <input value={redirectedUrl} onChange={(e) => setRedirectedUrl(e.target.value)} placeholder="粘贴授权回调 URL" style={{ width: '100%', marginTop: 8, height: 34, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
          <button type="button" onClick={async () => {
            const res = await api.exchangeOauth(redirectedUrl)
            setToolStatus(res.success ? '已换取 token' : (res.error || '换取失败'))
          }} style={{ marginTop: 8, height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>换取 Refresh Token</button>
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
            项目 {(projectsQuery.data || []).length} 个
            {(projectsQuery.data || []).slice(0, 5).map((p) => ` · ${p.name || p.project_key || '未命名'}`)}
          </div>
          {toolStatus && <div style={{ marginTop: 8, fontSize: 12 }}>{toolStatus}</div>}
          <div style={{ marginTop: 18, fontSize: 15, fontWeight: 700 }}>临时邮箱</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button type="button" onClick={async () => {
              const res = await api.generateTempEmail({ provider: 'gptmail' })
              setToolStatus(res.email ? `已生成 ${res.email}` : (res.error || '生成失败'))
              await qc.invalidateQueries({ queryKey: ['temp-emails'] })
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>生成 GPTMail</button>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
            {(tempQuery.data || []).slice(0, 8).map((item) => item.email || item.address).filter(Boolean).join(' · ') || '暂无临时邮箱'}
          </div>
          <div style={{ marginTop: 18, fontSize: 15, fontWeight: 700 }}>项目</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input value={projectKey} onChange={(e) => setProjectKey(e.target.value)} placeholder="project key" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <button type="button" onClick={async () => {
              const res = await api.startProject({ project_key: projectKey, name: projectKey })
              setToolStatus(res.success === false ? (res.error || '创建失败') : '项目已启动')
              await qc.invalidateQueries({ queryKey: ['projects'] })
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>启动项目</button>
          </div>
          <div style={{ marginTop: 18, fontSize: 15, fontWeight: 700 }}>WebDAV 备份</div>
          <input value={webdavUrl} onChange={(e) => setWebdavUrl(e.target.value)} placeholder="https://dav.example.com/backup/" style={{ width: '100%', marginTop: 8, height: 34, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input value={webdavUser} onChange={(e) => setWebdavUser(e.target.value)} placeholder="用户名" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
            <input value={webdavPass} onChange={(e) => setWebdavPass(e.target.value)} type="password" placeholder="密码" style={{ flex: 1, height: 32, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)', padding: '0 8px' }} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button type="button" onClick={async () => {
              const res = await api.testWebdav({ url: webdavUrl, username: webdavUser, password: webdavPass })
              setToolStatus(res.success ? 'WebDAV 测试成功' : (res.error || '测试失败'))
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)' }}>测试备份</button>
            <button type="button" onClick={async () => {
              const res = await api.uploadWebdav({ url: webdavUrl, username: webdavUser, password: webdavPass })
              setToolStatus(res.success ? (res.message || '已上传备份') : (res.error || '上传失败'))
            }} style={{ height: 32, padding: '0 10px', borderRadius: 8, border: 0, background: 'var(--blue)', color: '#fff' }}>立即备份</button>
          </div>
          </>}
          {section === 'appearance' && <>
          <div style={{ marginTop: 22, fontSize: 18, fontWeight: 720 }}>外观</div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button onClick={() => setTheme('light')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 12, borderRadius: 11, border: `1px solid ${theme === 'light' ? 'var(--blue)' : 'var(--line)'}`, background: 'var(--surface)' }}>
              <Sun size={18} /> 亮色
            </button>
            <button onClick={() => setTheme('dark')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 12, borderRadius: 11, border: `1px solid ${theme === 'dark' ? 'var(--blue)' : 'var(--line)'}`, background: 'var(--surface)' }}>
              <Moon size={18} /> 深夜
            </button>
          </div>
          </>}
          {section === 'general' && (
            <div style={{ color: 'var(--muted)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Inbox size={14} /> 旧版完整管理界面仍可从 /legacy 进入。规范见仓库根目录 DESIGN.md。
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
