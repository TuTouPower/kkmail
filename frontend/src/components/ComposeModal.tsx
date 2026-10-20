import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api } from '../api/client'
import { fetchAccounts, queryKeys } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { ensureSuccess, errorMessage } from '../lib/actions'

export default function ComposeModal() {
  const composeOpen = useMailStore((s) => s.composeOpen)
  const composeSeq = useMailStore((s) => s.composeSeq)
  if (!composeOpen) return null
  // Remount per open so the form state is initialised from the current draft.
  return <ComposeForm key={composeSeq} />
}

function ComposeForm() {
  const { setComposeOpen, composeMode, composeDraft, view } = useMailStore()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []
  const [accountId, setAccountId] = useState(() => composeDraft.accountId || (view.type === 'accountFolder' ? view.accountId : 0))
  const [to, setTo] = useState(composeDraft.to)
  const [cc, setCc] = useState('')
  const [subject, setSubject] = useState(composeDraft.subject)
  const [body, setBody] = useState(composeDraft.body)
  const [status, setStatus] = useState('')
  const [sending, setSending] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSending(true)
    setStatus('')
    try {
      const recipients = [to, cc].filter(Boolean).join(', ')
      ensureSuccess(await api.sendOutlookMail({ account_id: accountId, recipients, subject, body }), '发送失败')
      setStatus('已提交发送（Graph 返回 202 表示已受理，不代表已送达）')
      setTimeout(() => setComposeOpen(false), 900)
    } catch (err: unknown) {
      setStatus(errorMessage(err, '发送失败。仅已完成 Graph 授权的 Outlook 账号可发信。'))
    } finally {
      setSending(false)
    }
  }

  const title = composeMode === 'reply' ? '回复' : composeMode === 'forward' ? '转发' : '新邮件'

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 120, background: 'rgba(0,0,0,.46)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 18 }} onClick={(e) => { if (e.target === e.currentTarget) setComposeOpen(false) }}>
      <form onSubmit={submit} style={{ width: 'min(720px, 100%)', background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 15, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '13px 16px', borderBottom: '1px solid var(--line)' }}>
          <strong style={{ flex: 1 }}>{title}</strong>
          <button type="button" onClick={() => setComposeOpen(false)} style={{ border: 0, background: 'transparent', color: 'var(--muted)' }}><X size={16} /></button>
        </div>
        <div style={{ padding: '8px 18px' }}>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ width: 64, color: 'var(--muted)' }}>发件账户</span>
            <select value={accountId || ''} onChange={(e) => setAccountId(Number(e.target.value))} style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }}>
              <option value="">选择 Outlook Graph 账号</option>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.email}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ width: 64, color: 'var(--muted)' }}>收件人</span>
            <input value={to} onChange={(e) => setTo(e.target.value)} required placeholder="name@example.com" style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }} />
          </label>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ width: 64, color: 'var(--muted)' }}>抄送</span>
            <input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="可选，Graph 基础发信会合并到收件人" style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }} />
          </label>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ width: 64, color: 'var(--muted)' }}>主题</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }} />
          </label>
        </div>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="撰写邮件…" style={{ width: '100%', minHeight: 180, border: 0, background: 'var(--surface)', padding: 18, resize: 'vertical' }} />
        <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid var(--line)', alignItems: 'center' }}>
          <button type="submit" disabled={sending || !accountId} style={{ height: 35, padding: '0 15px', border: 0, borderRadius: 9, background: 'var(--blue)', color: '#fff' }}>{sending ? '发送中…' : '发送'}</button>
          <button type="button" onClick={() => setComposeOpen(false)} style={{ height: 35, padding: '0 12px', border: '1px solid var(--line)', borderRadius: 9, background: 'var(--surface)' }}>取消</button>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)' }}>{status || '仅 Outlook Graph 授权账号可发送'}</span>
        </div>
      </form>
    </div>
  )
}
