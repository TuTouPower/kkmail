import { useState } from 'react'
import { X, Sun, Moon, Inbox, Settings as SettingsIcon } from 'lucide-react'
import { useMailStore } from '../store/mailStore'

export default function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { theme, setTheme, accounts } = useMailStore()
  const [tab, setTab] = useState<'accounts' | 'appearance' | 'general'>('accounts')

  if (!open) return null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 110,
        background: 'rgba(0,0,0,.46)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 18,
        backdropFilter: 'blur(5px)',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <section
        style={{
          width: 'min(720px, 100%)',
          height: 'min(620px, 84dvh)',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--surface)',
          border: '1px solid var(--line-strong)',
          borderRadius: 15,
          boxShadow: 'var(--shadow)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '13px 16px',
            borderBottom: '1px solid var(--line)',
            background: 'var(--surface-2)',
          }}
        >
          <SettingsIcon size={16} />
          <strong style={{ flex: 1, fontSize: 13 }}>设置</strong>
          <button onClick={onClose} style={{ height: 28, width: 28, display: 'grid', placeItems: 'center', border: 0, borderRadius: 7, background: 'transparent', color: 'var(--muted)' }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ display: 'flex', minHeight: 0, flex: 1 }}>
          <nav style={{ width: 168, flex: '0 0 168px', padding: '13px 10px', borderRight: '1px solid var(--line)', background: 'var(--surface-2)' }}>
            <button className={`settings-tab ${tab === 'accounts' ? 'active' : ''}`} onClick={() => setTab('accounts')} style={tabStyle(tab === 'accounts')}>
              <Inbox size={16} />
              <span>账户管理</span>
            </button>
            <button className={`settings-tab ${tab === 'appearance' ? 'active' : ''}`} onClick={() => setTab('appearance')} style={tabStyle(tab === 'appearance')}>
              <Sun size={16} />
              <span>外观</span>
            </button>
            <button className={`settings-tab ${tab === 'general' ? 'active' : ''}`} onClick={() => setTab('general')} style={tabStyle(tab === 'general')}>
              <SettingsIcon size={16} />
              <span>通用</span>
            </button>
          </nav>
          <div style={{ minWidth: 0, flex: 1, overflow: 'auto', padding: '22px 24px' }}>
            {tab === 'accounts' && (
              <>
                <div style={{ fontSize: 18, fontWeight: 720, letterSpacing: '-0.3px', margin: '0 0 6px' }}>账户管理</div>
                <p style={{ margin: '0 0 18px', color: 'var(--muted)', fontSize: 12, lineHeight: 1.65 }}>
                  集中查看已配置的邮箱账户。正式版可在这里添加、重新授权或移除账户。
                </p>
                <div style={{ border: '1px solid var(--line)', borderRadius: 11, overflow: 'hidden' }}>
                  {accounts.map((a) => (
                    <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 11px', minHeight: 51, borderBottom: '1px solid var(--line)' }}>
                      <span style={{ width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: 8, color: '#fff', fontSize: 10, fontWeight: 800, background: a.color }}>
                        {a.provider === '网易 163' ? '163' : a.provider === 'Outlook' ? 'O' : 'G'}
                      </span>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <strong style={{ fontSize: 12, fontWeight: 600 }}>{a.email}</strong>
                        <div style={{ fontSize: 10, color: 'var(--muted)' }}>{a.provider} · {a.group}</div>
                      </div>
                      <span style={{ fontSize: 10, color: 'var(--muted)', background: 'var(--surface-2)', padding: '4px 6px', borderRadius: 6 }}>演示</span>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 13, fontSize: 10, color: 'var(--muted)' }}>支持 Gmail、Outlook、网易 163（演示）</div>
              </>
            )}
            {tab === 'appearance' && (
              <>
                <div style={{ fontSize: 18, fontWeight: 720, letterSpacing: '-0.3px', margin: '0 0 6px' }}>外观</div>
                <p style={{ margin: '0 0 18px', color: 'var(--muted)', fontSize: 12, lineHeight: 1.65 }}>
                  选择适合当前环境的界面主题。主题偏好会保存在此浏览器中。
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <button
                    onClick={() => setTheme('light')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 11,
                      padding: 12,
                      border: `1px solid ${theme === 'light' ? 'var(--blue)' : 'var(--line)'}`,
                      borderRadius: 11,
                      background: 'var(--surface)',
                      textAlign: 'left',
                    }}
                  >
                    <Sun size={20} />
                    <div>
                      <strong style={{ fontSize: 12 }}>亮色模式</strong>
                      <div style={{ fontSize: 10, color: 'var(--muted)' }}>明亮背景，适合白天使用</div>
                    </div>
                  </button>
                  <button
                    onClick={() => setTheme('dark')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 11,
                      padding: 12,
                      border: `1px solid ${theme === 'dark' ? 'var(--blue)' : 'var(--line)'}`,
                      borderRadius: 11,
                      background: 'var(--surface)',
                      textAlign: 'left',
                    }}
                  >
                    <Moon size={20} />
                    <div>
                      <strong style={{ fontSize: 12 }}>深夜模式</strong>
                      <div style={{ fontSize: 10, color: 'var(--muted)' }}>深色背景，降低环境亮度</div>
                    </div>
                  </button>
                </div>
              </>
            )}
            {tab === 'general' && (
              <>
                <div style={{ fontSize: 18, fontWeight: 720, letterSpacing: '-0.3px', margin: '0 0 6px' }}>通用</div>
                <p style={{ margin: '0 0 18px', color: 'var(--muted)', fontSize: 12, lineHeight: 1.65 }}>
                  管理邮件列表和键盘操作偏好。
                </p>
                <div style={{ fontSize: 12 }}>键盘快捷键：N 写邮件 · Esc 关闭窗口 · ⌘/Ctrl+K 搜索</div>
              </>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 16px', borderTop: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          <span style={{ fontSize: 10, color: 'var(--muted)' }}>当前为前端演示，账户连接与设置同步尚未接入后端。</span>
          <button
            onClick={onClose}
            style={{ height: 35, padding: '0 15px', border: 0, borderRadius: 9, background: 'var(--blue)', color: '#fff', fontWeight: 650 }}
          >
            完成
          </button>
        </div>
      </section>
    </div>
  )
}

function tabStyle(active: boolean): React.CSSProperties {
  return {
    width: '100%',
    height: 38,
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    padding: '0 10px',
    margin: '2px 0',
    border: 0,
    borderRadius: 8,
    background: active ? 'var(--selected)' : 'transparent',
    color: active ? 'var(--text)' : 'var(--subtle)',
    textAlign: 'left',
    fontSize: 12,
    fontWeight: active ? 650 : 400,
  }
}
