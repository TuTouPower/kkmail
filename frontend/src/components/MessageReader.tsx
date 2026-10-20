import { useEffect, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MailOpen, Trash2, Flag, ArrowLeft } from 'lucide-react'
import { fetchAccounts, findCachedMail, flagOptimistic, markReadOptimistic, queryClient, queryKeys, removeCachedMail } from '../api/queries'
import { fetchMailCoreMessage, mailCoreAttachmentUrl, mailCoreToMailDetail, postMailCoreMessageTrash } from '../api/mailCore'
import { mailKey } from '../lib/mailKey'
import { useMailStore } from '../store/mailStore'
import { confirmAction, errorMessage } from '../lib/actions'
import { MAIL_IFRAME_SANDBOX, buildMailSrcdoc, isHtmlBody } from '../lib/mailBody'
import { formatReaderDate } from '../lib/listDate'
import { displayName } from '../lib/displayName'

export default function MessageReader() {
  const { selectedKey, setMobileView } = useMailStore()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []
  const [actionStatus, setActionStatus] = useState('')
  const [loadRemoteImages, setLoadRemoteImages] = useState(false)
  useEffect(() => {
    setLoadRemoteImages(false)
  }, [selectedKey])
  // Re-render when any cached list changes (optimistic read/delete updates).
  const cache = queryClient.getQueryCache()
  useSyncExternalStore((cb) => cache.subscribe(cb), () => findCachedMail(selectedKey))
  const selected = findCachedMail(selectedKey)

  const detailQuery = useQuery({
    queryKey: selected
      ? ['detail', 'mail-core', selected.id]
      : ['detail', 'none'],
    queryFn: async ({ signal }) => {
      const d = await fetchMailCoreMessage(selected!.id, signal)
      return mailCoreToMailDetail(d)
    },
    retry: false,
    enabled: !!selected?.id,
    // Never keep the previous message body while switching selection.
    placeholderData: undefined,
  })

  if (!selected) {
    return (
      <section className="reader-pane" aria-label="邮件正文">
        <div className="reader-toolbar"><div className="reader-location">未选择邮件</div></div>
        <div className="reader-scroll">
          <div className="no-message">
            <strong>未选择邮件</strong>
            <span>从邮件列表中选择一封邮件以查看内容。</span>
          </div>
        </div>
      </section>
    )
  }

  const detail = detailQuery.data
  const body = detail?.body || selected.body_preview || ''
  const html = !!detail?.body && isHtmlBody(detail.body_type)

  async function markCurrent() {
    if (!selected) return
    try {
      await markReadOptimistic([selected])
      setActionStatus('')
    } catch (err) {
      setActionStatus(errorMessage(err, '标记失败'))
    }
  }

  async function trashCurrent() {
    if (!selected) return
    if (!confirmAction(`将「${selected.subject}」移到废纸篓？`)) return
    try {
      await postMailCoreMessageTrash(selected.id)
      setActionStatus('')
      removeCachedMail([mailKey(selected)])
      await queryClient.invalidateQueries({ queryKey: ['mail-core'] })
    } catch (err) {
      setActionStatus(errorMessage(err, '删除失败'))
    }
  }

  async function toggleFlagged() {
    if (!selected) return
    try {
      await flagOptimistic(selected, !selected.is_flagged)
      setActionStatus('')
    } catch (err) {
      setActionStatus(errorMessage(err, '标记失败'))
    }
  }

  return (
    <section className="reader-pane" aria-label="邮件正文">
      <div className="reader-toolbar">
        <button className="reader-action mobile-only" title="返回列表" aria-label="返回列表" onClick={() => setMobileView('list')}><ArrowLeft size={18} /></button>
        <div className="reader-location">{selected.accountEmail}</div>
        <div className="reader-toolbar-actions">
          <button className="reader-action" title="标为已读" aria-label="标为已读" onClick={markCurrent} disabled={selected.is_read}><MailOpen size={18} /></button>
          <button className="reader-action" title="移到废纸篓" aria-label="移到废纸篓" onClick={trashCurrent}><Trash2 size={18} /></button>
          <button
            className="reader-action"
            title={selected.is_flagged ? '取消标记' : '标记邮件'}
            aria-label={selected.is_flagged ? '取消标记' : '标记邮件'}
            aria-pressed={selected.is_flagged}
            onClick={toggleFlagged}
          ><Flag size={18} /></button>
        </div>
      </div>
      <div className="reader-scroll">
        <div className="message-paper">
          <div className="detail-subject">{detail?.subject || selected.subject}</div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            <strong>{displayName(detail?.from || selected.from)}</strong>
            <span style={{ color: 'var(--muted)' }}> · {formatReaderDate(detail?.date || selected.date)}</span>
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: detail?.cc ? 4 : 16, overflowWrap: 'anywhere' }}>
            收件人：{detail?.to || selected.to || accounts.find((a) => a.email === selected.accountEmail)?.email || selected.accountEmail}
          </div>
          {detail?.cc && (
            <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 16, overflowWrap: 'anywhere' }}>抄送：{detail.cc}</div>
          )}
          {actionStatus && <div role="status" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 8 }}>{actionStatus}</div>}
          {detailQuery.isLoading && <div style={{ color: 'var(--muted)' }}>正在加载正文…</div>}
          {detailQuery.error && <div style={{ color: 'var(--red)' }}>{String((detailQuery.error as Error).message)}</div>}
          {html ? (
            <>
              {!loadRemoteImages && /<img\b[^>]+src\s*=\s*["']https?:/i.test(body) && (
                <div style={{ fontSize: 12, marginBottom: 10, padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 8, background: 'var(--panel, #f7f7f8)' }}>
                  远程图片已拦截（防追踪）。
                  <button type="button" style={{ marginLeft: 8 }} onClick={() => setLoadRemoteImages(true)}>
                    仅此邮件允许加载
                  </button>
                </div>
              )}
              <iframe
                className="email-body email-body-frame"
                title="邮件正文"
                sandbox={MAIL_IFRAME_SANDBOX}
                referrerPolicy="no-referrer"
                srcDoc={buildMailSrcdoc(body, { loadRemoteImages })}
                style={{ width: '100%', minHeight: 420, border: 0, background: '#fff', borderRadius: 8 }}
              />
            </>
          ) : (
            <div className="email-body email-body-text">{body}</div>
          )}
          {(detail?.attachments || []).length > 0 && (
            <div className="attachment-list" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 18 }}>
              {detail!.attachments!.map((att, i) => {
                const href = att.id ? mailCoreAttachmentUrl(att.id) : undefined
                return (
                  <a key={att.id || i} href={href} style={{ padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 9, color: 'inherit', textDecoration: 'none' }}>
                    <strong>{att.name || '附件'}</strong>
                    {att.size ? <small style={{ display: 'block', color: 'var(--muted)' }}>{att.size} B</small> : null}
                  </a>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
