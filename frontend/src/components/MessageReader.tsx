import { useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Reply, ReplyAll, Forward, MailOpen, Trash2, Flag, Folder, Archive, ShieldAlert, ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import { fetchAccounts, fetchEmailDetail, findCachedMail, flagOptimistic, markReadOptimistic, queryClient, queryKeys, type MailItem } from '../api/queries'
import { fetchMailCoreMessage, mailCoreAttachmentUrl, mailCoreToMailDetail } from '../api/mailCore'
import { isMailCoreEnabled } from '../lib/mailCoreFlag'
import { mailKey } from '../lib/mailKey'
import { useMailStore } from '../store/mailStore'
import { confirmAction, ensureSuccess, errorMessage } from '../lib/actions'
import { replyAllRecipients, replyRecipient } from '../lib/recipients'
import { MAIL_IFRAME_SANDBOX, buildMailSrcdoc, htmlToText, isHtmlBody } from '../lib/mailBody'
import { formatReaderDate } from '../lib/listDate'
import { displayName } from '../lib/displayName'

export default function MessageReader() {
  const { selectedKey, openCompose, flaggedIds, toggleFlag, setMobileView } = useMailStore()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []
  const [actionStatus, setActionStatus] = useState('')
  // Re-render when any cached list changes (optimistic read/delete updates).
  const cache = queryClient.getQueryCache()
  useSyncExternalStore((cb) => cache.subscribe(cb), () => findCachedMail(selectedKey))
  const selected = findCachedMail(selectedKey)

  const preferMailCoreDetail = isMailCoreEnabled() && (!!selected?.id_mode?.includes('mail_core') || selected?.id_mode === 'mail_core')
  const detailQuery = useQuery({
    queryKey: selected
      ? ['detail', preferMailCoreDetail ? 'mail-core' : 'flask', selected.accountEmail, selected.id, selected.folder || 'inbox', selected.id_mode || '']
      : ['detail', 'none'],
    queryFn: async ({ signal }) => {
      if (preferMailCoreDetail) {
        try {
          const d = await fetchMailCoreMessage(selected!.id, signal)
          return mailCoreToMailDetail(d)
        } catch (err) {
          // Legacy Flask fallback when mail-core detail is unavailable.
          if (selected!.accountEmail && selected!.id_mode !== 'mail_core') {
            return fetchEmailDetail(selected!.accountEmail, selected!.id, selected!.folder || 'inbox', selected!.id_mode || '', signal)
          }
          // mail_core ids are UUIDs — Flask cannot serve them; rethrow.
          throw err
        }
      }
      return fetchEmailDetail(selected!.accountEmail, selected!.id, selected!.folder || 'inbox', selected!.id_mode || '', signal)
    },
    retry: false,
    enabled: !!selected?.id && (!!selected?.accountEmail || preferMailCoreDetail),
  })
  const useMailCoreDetail = preferMailCoreDetail && !detailQuery.isError

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
  const quotedBody = html ? htmlToText(body) : body

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
    const folder = selected.folder || 'inbox'
    const warning = folder === 'deleteditems' ? '废纸篓中的邮件将被永久删除，无法恢复。' : '邮件将移到废纸篓（IMAP 账户可能直接永久删除）。'
    if (!confirmAction(`删除「${selected.subject}」？${warning}`)) return
    try {
      ensureSuccess(await api.deleteEmails({ email: selected.accountEmail, folder, items: [{ id: selected.id, folder, id_mode: selected.id_mode || '' }] }), '删除失败')
      setActionStatus('')
      const gone = mailKey(selected)
      queryClient.setQueriesData<MailItem[]>({ queryKey: ['emails'] }, (list) => list?.filter((m) => mailKey(m) !== gone))
      await queryClient.invalidateQueries({ queryKey: ['emails', selected.accountEmail] })
    } catch (err) {
      setActionStatus(errorMessage(err, '删除失败'))
    }
  }

  return (
    <section className="reader-pane" aria-label="邮件正文">
      <div className="reader-toolbar">
        <button className="reader-action mobile-only" title="返回列表" aria-label="返回列表" onClick={() => setMobileView('list')}><ArrowLeft size={18} /></button>
        <div className="reader-location">{selected.accountEmail}</div>
        <div className="reader-toolbar-actions">
          <button className="reader-action" title="回复" aria-label="回复" onClick={() => openCompose('reply', {
            to: replyRecipient(detail?.from || selected.from),
            subject: `Re: ${detail?.subject || selected.subject}`,
            body: `\n\n—— 原始邮件 ——\n发件人：${selected.from}\n主题：${detail?.subject || selected.subject}\n\n${quotedBody}`,
            accountId: selected.accountId,
          })}><Reply size={18} /></button>
          <button className="reader-action" title="回复全部" aria-label="回复全部" onClick={() => openCompose('replyAll', {
            to: replyAllRecipients(detail?.from || selected.from, [detail?.to || selected.to, detail?.cc], selected.accountEmail),
            subject: `Re: ${detail?.subject || selected.subject}`,
            body: `\n\n—— 原始邮件 ——\n发件人：${selected.from}\n主题：${detail?.subject || selected.subject}\n\n${quotedBody}`,
            accountId: selected.accountId,
          })}><ReplyAll size={18} /></button>
          <button className="reader-action" title="转发" aria-label="转发" onClick={() => openCompose('forward', {
            subject: `Fwd: ${detail?.subject || selected.subject}`,
            body: `\n\n—— 转发邮件 ——\n发件人：${selected.from}\n主题：${detail?.subject || selected.subject}\n\n${quotedBody}`,
            accountId: selected.accountId,
          })}><Forward size={18} /></button>
          <span style={{ height: 22, width: 1, background: 'var(--line-strong)', margin: '0 3px' }} />
          <button className="reader-action" title="标为已读" aria-label="标为已读" onClick={markCurrent} disabled={selected.is_read}><MailOpen size={18} /></button>
          <button className="reader-action" title="归档（后端暂无归档接口）" aria-label="归档" disabled aria-disabled="true"><Archive size={18} /></button>
          <button className="reader-action" title="移到废纸篓" aria-label="移到废纸篓" onClick={trashCurrent}><Trash2 size={18} /></button>
          <button className="reader-action" title="标记为垃圾邮件（后端暂无移动接口）" aria-label="标记为垃圾邮件" disabled aria-disabled="true"><ShieldAlert size={18} /></button>
          <span style={{ height: 22, width: 1, background: 'var(--line-strong)', margin: '0 3px' }} />
          <button className="reader-action" title="移动到文件夹（后端暂无移动接口）" aria-label="移动到文件夹" disabled aria-disabled="true"><Folder size={18} /></button>
          <button className="reader-action" title={flaggedIds.includes(selectedKey || '') ? '取消标记' : '标记邮件'} aria-label={flaggedIds.includes(selectedKey || '') ? '取消标记' : '标记邮件'} aria-pressed={flaggedIds.includes(selectedKey || '')} onClick={() => {
              if (!selected || !selectedKey) return
              const next = !flaggedIds.includes(selectedKey)
              void flagOptimistic(selected, next, toggleFlag).catch((err) =>
                setActionStatus(errorMessage(err, '标记失败')),
              )
            }}><Flag size={18} /></button>
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
            <iframe
              className="email-body email-body-frame"
              title="邮件正文"
              sandbox={MAIL_IFRAME_SANDBOX}
              referrerPolicy="no-referrer"
              srcDoc={buildMailSrcdoc(body, { loadRemoteImages: !useMailCoreDetail })}
              style={{ width: '100%', minHeight: 420, border: 0, background: '#fff', borderRadius: 8 }}
            />
          ) : (
            <div className="email-body email-body-text">{body}</div>
          )}
          {(detail?.attachments || []).length > 0 && (
            <div className="attachment-list" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 18 }}>
              {detail!.attachments!.map((att, i) => {
                const href = att.id
                  ? (useMailCoreDetail
                      ? mailCoreAttachmentUrl(att.id)
                      : api.attachmentUrl(selected.accountEmail, selected.id, att.id, selected.folder || 'inbox', selected.id_mode || ''))
                  : undefined
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
