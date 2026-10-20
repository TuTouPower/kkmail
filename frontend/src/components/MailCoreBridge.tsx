import { useCallback, useEffect, useState } from 'react'
import { fetchMailCoreHealth, fetchMailCoreInbox, subscribeMailCoreEvents, type MailCoreMessage } from '../api/mailCore'
import { queryClient } from '../api/queries'
import { isMailCoreEnabled, mailCoreBaseUrl } from '../lib/mailCoreFlag'

/**
 * Optional mail-core bridge panel. Only mounts when VITE_MAIL_CORE is enabled.
 * Does not replace the Flask-backed MessageList; opens as a side experimental panel.
 */
export default function MailCoreBridge() {
  const enabled = isMailCoreEnabled()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<MailCoreMessage[]>([])
  const [status, setStatus] = useState('')
  const [sseNote, setSseNote] = useState('')

  const reload = useCallback(async () => {
    setStatus('加载中…')
    try {
      const health = await fetchMailCoreHealth()
      const page = await fetchMailCoreInbox(40)
      setItems(page.items)
      setStatus(`mail-core ${health.status} · ${page.items.length} 封 · ${mailCoreBaseUrl()}`)
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'mail-core 不可用')
      setItems([])
    }
  }, [])

  useEffect(() => {
    if (!enabled || !open) return
    void reload()
    const stop = subscribeMailCoreEvents(
      (type) => {
        setSseNote(`SSE: ${type}`)
        const refresh =
          type === 'message.upserted' ||
          type === 'message.removed' ||
          type === 'folder.stats_updated' ||
          type === 'mail.changed' ||
          type === 'folder.stats.changed' ||
          type === 'client.resync_hint' ||
          type === 'sync.completed'
        if (refresh) {
          void queryClient.invalidateQueries({ queryKey: ['mail-core', 'inbox'] })
          void reload()
        }
      },
      () => setSseNote('SSE 断开'),
    )
    return stop
  }, [enabled, open, reload])

  if (!enabled) return null

  return (
    <>
      <button
        type="button"
        className="mail-core-bridge-toggle"
        title="打开 mail-core 实验收件箱"
        aria-label="打开 mail-core 实验收件箱"
        onClick={() => setOpen((v) => !v)}
        style={{
          position: 'fixed',
          right: 16,
          bottom: 16,
          zIndex: 40,
          borderRadius: 999,
          padding: '10px 14px',
          border: '1px solid var(--line)',
          background: 'var(--accent)',
          color: '#fff',
          fontSize: 12,
          fontWeight: 650,
          boxShadow: '0 8px 24px rgba(0,0,0,.25)',
        }}
      >
        {open ? '关闭 mail-core' : 'mail-core 实验'}
      </button>
      {open && (
        <aside
          className="mail-core-bridge-panel"
          aria-label="mail-core 统一收件箱"
          style={{
            position: 'fixed',
            right: 16,
            bottom: 64,
            width: 360,
            maxHeight: '70dvh',
            overflow: 'auto',
            zIndex: 40,
            borderRadius: 14,
            border: '1px solid var(--line)',
            background: 'var(--reader)',
            boxShadow: '0 16px 40px rgba(0,0,0,.35)',
            padding: 12,
          }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
            <strong style={{ flex: 1, fontSize: 13 }}>mail-core 收件箱</strong>
            <button type="button" onClick={() => void reload()} style={{ fontSize: 12 }}>刷新</button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>{status}</div>
          {sseNote && <div style={{ fontSize: 11, color: 'var(--accent)', marginBottom: 8 }}>{sseNote}</div>}
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {items.map((m) => (
              <li
                key={m.id}
                style={{
                  padding: '8px 0',
                  borderBottom: '1px solid var(--line)',
                  fontSize: 12,
                }}
              >
                <div style={{ fontWeight: m.is_read ? 500 : 720 }}>
                  {m.from_name || m.from_address}
                </div>
                <div>{m.subject || '（无主题）'}</div>
                <div style={{ color: 'var(--muted)' }}>{m.snippet}</div>
              </li>
            ))}
            {items.length === 0 && (
              <li style={{ color: 'var(--muted)', fontSize: 12 }}>暂无本地权威邮件（需先跑 mail-core 同步）</li>
            )}
          </ul>
        </aside>
      )}
    </>
  )
}
