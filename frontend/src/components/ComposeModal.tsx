import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api } from '../api/client'
import { fetchAccounts, queryKeys } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { ensureSuccess, errorMessage } from '../lib/actions'
import { canSendFrom } from '../lib/accounts'

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
  const selectedAccount = accounts.find((a) => a.id === accountId)
  const sendable = accounts.filter((a) => canSendFrom(a))
  const canSend = canSendFrom(selectedAccount)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setComposeOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setComposeOpen])

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
      setStatus(errorMessage(err, '发送失败'))
    } finally {
      setSending(false)
    }
  }

  const title = composeMode === 'reply' ? '回复' : composeMode === 'replyAll' ? '回复全部' : composeMode === 'forward' ? '转发' : '新邮件'
  const hint = !accountId
    ? (sendable.length ? '请选择发件账户' : '没有可发信的账户：目前仅支持已授权的 Outlook 账号发信')
    : canSend
      ? '通过 Outlook（Microsoft Graph）发送纯文本邮件'
      : 'IMAP 账户暂不支持发信，请选择 Outlook 账号'

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 120, background: 'rgba(0,0,0,.46)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 18 }} onClick={(e) => { if (e.target === e.currentTarget) setComposeOpen(false) }}>
      <form className="compose-dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="compose-title" style={{ width: 'min(720px, 100%)', background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 15, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '13px 16px', borderBottom: '1px solid var(--line)' }}>
          <strong id="compose-title" style={{ flex: 1 }}>{title}</strong>
          <button type="button" title="关闭（Esc）" aria-label="关闭" onClick={() => setComposeOpen(false)} style={{ border: 0, background: 'transparent', color: 'var(--muted)' }}><X size={16} /></button>
        </div>
        <div style={{ padding: '8px 18px' }}>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ flex: '0 0 64px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>发件账户</span>
            <select name="accountId" value={accountId || ''} onChange={(e) => setAccountId(Number(e.target.value))} style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }}>
              <option value="">选择发件账户</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id} disabled={!canSendFrom(a)}>
                  {a.email}{canSendFrom(a) ? '' : '（IMAP，暂不支持发信）'}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ flex: '0 0 64px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>收件人</span>
            <input name="to" value={to} onChange={(e) => setTo(e.target.value)} required placeholder="name@example.com" style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }} />
          </label>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ flex: '0 0 64px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>抄送</span>
            <input name="cc" value={cc} onChange={(e) => setCc(e.target.value)} placeholder="可选，多个地址用逗号分隔（发送时并入收件人）" style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }} />
          </label>
          <label style={{ display: 'flex', gap: 12, alignItems: 'center', minHeight: 40, borderBottom: '1px solid var(--line)' }}>
            <span style={{ flex: '0 0 64px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>主题</span>
            <input name="subject" value={subject} onChange={(e) => setSubject(e.target.value)} style={{ flex: 1, border: 0, background: 'transparent', padding: '10px 0' }} />
          </label>
        </div>
        <textarea name="body" value={body} onChange={(e) => setBody(e.target.value)} placeholder="撰写邮件…" style={{ width: '100%', minHeight: 180, border: 0, background: 'var(--surface)', padding: 18, resize: 'vertical' }} />
        <div className="dialog-actions" style={{ padding: 12, borderTop: '1px solid var(--line)' }}>
          <button type="submit" disabled={sending || !canSend} style={{ height: 35, padding: '0 15px', border: 0, borderRadius: 9, background: 'var(--blue)', color: '#fff' }}>{sending ? '发送中…' : '发送'}</button>
          <button type="button" onClick={() => setComposeOpen(false)} style={{ height: 35, padding: '0 12px', border: '1px solid var(--line)', borderRadius: 9, background: 'var(--surface)' }}>取消</button>
          <span role="status" className="dialog-hint">{status || hint}</span>
        </div>
      </form>
    </div>
  )
}
