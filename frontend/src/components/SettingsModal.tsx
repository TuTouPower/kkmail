import { useQuery } from '@tanstack/react-query'
import { X, Sun, Moon, Inbox, Settings as SettingsIcon } from 'lucide-react'
import { fetchAccounts, queryKeys } from '../api/queries'
import { providerBadge, providerColor, useMailStore } from '../store/mailStore'

export default function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { theme, setTheme } = useMailStore()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts, enabled: open })
  const accounts = accountsQuery.data || []

  if (!open) return null

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 110, background: 'rgba(0,0,0,.46)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 18, backdropFilter: 'blur(5px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <section style={{ width: 'min(720px, 100%)', height: 'min(620px, 84dvh)', display: 'flex', flexDirection: 'column', background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 15, boxShadow: 'var(--shadow)', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '13px 16px', borderBottom: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          <SettingsIcon size={16} />
          <strong style={{ flex: 1, fontSize: 13 }}>设置</strong>
          <button onClick={onClose} style={{ height: 28, width: 28, display: 'grid', placeItems: 'center', border: 0, borderRadius: 7, background: 'transparent', color: 'var(--muted)' }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ minWidth: 0, flex: 1, overflow: 'auto', padding: '22px 24px' }}>
          <div style={{ fontSize: 18, fontWeight: 720, margin: '0 0 6px' }}>账户管理</div>
          <p style={{ margin: '0 0 18px', color: 'var(--muted)', fontSize: 12 }}>来自现有 Flask 账户库。添加、授权、IMAP 配置仍走后端已有流程。</p>
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
          <div style={{ marginTop: 22, fontSize: 18, fontWeight: 720 }}>外观</div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button onClick={() => setTheme('light')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 12, borderRadius: 11, border: `1px solid ${theme === 'light' ? 'var(--blue)' : 'var(--line)'}`, background: 'var(--surface)' }}>
              <Sun size={18} /> 亮色
            </button>
            <button onClick={() => setTheme('dark')} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 12, borderRadius: 11, border: `1px solid ${theme === 'dark' ? 'var(--blue)' : 'var(--line)'}`, background: 'var(--surface)' }}>
              <Moon size={18} /> 深夜
            </button>
          </div>
          <div style={{ marginTop: 18, color: 'var(--muted)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Inbox size={14} /> 旧版完整管理界面仍可从 /legacy 进入。
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '12px 16px', borderTop: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          <button onClick={onClose} style={{ height: 35, padding: '0 15px', border: 0, borderRadius: 9, background: 'var(--blue)', color: '#fff', fontWeight: 650 }}>完成</button>
        </div>
      </section>
    </div>
  )
}
