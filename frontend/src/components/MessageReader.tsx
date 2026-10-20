import { useQuery } from '@tanstack/react-query'
import { Reply, ReplyAll, Forward, MailOpen, Trash2, Flag, Folder, Archive, ShieldAlert, ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import { fetchAccounts, fetchEmailDetail, markEmailsRead, queryClient, queryKeys, type MailItem } from '../api/queries'
import { useMailStore } from '../store/mailStore'

export default function MessageReader() {
  const { selectedKey, openCompose, flaggedIds, toggleFlag, setMobileView } = useMailStore()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []
  const cachedLists = queryClient.getQueriesData<MailItem[]>({ queryKey: ['emails'] })
  const selected = cachedLists
    .flatMap(([, list]) => list || [])
    .find((m) => `${m.accountEmail}:${m.id}` === selectedKey)

  const detailQuery = useQuery({
    queryKey: selected ? queryKeys.detail(selected.accountEmail, selected.id, selected.folder || 'inbox', selected.id_mode || '') : ['detail', 'none'],
    queryFn: () => fetchEmailDetail(selected!.accountEmail, selected!.id, selected!.folder || 'inbox', selected!.id_mode || ''),
    enabled: !!selected?.id && !!selected?.accountEmail,
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
  const html = (detail?.body_type || '').toLowerCase().includes('html') || body.trim().startsWith('<')

  async function markCurrent() {
    if (!selected) return
    await markEmailsRead(selected.accountEmail, [selected], selected.folder || 'inbox')
    await queryClient.invalidateQueries({ queryKey: ['emails'] })
  }

  return (
    <section className="reader-pane" aria-label="邮件正文">
      <div className="reader-toolbar">
        <button className="reader-action" title="返回列表" onClick={() => setMobileView('list')}><ArrowLeft size={15} /></button>
        <div className="reader-location">{selected.accountEmail}</div>
        <div className="reader-toolbar-actions">
          <button className="reader-action" title="回复" onClick={() => openCompose('reply', {
            to: selected.from.includes('@') ? selected.from : '',
            subject: `Re: ${detail?.subject || selected.subject}`,
            body: `\n\n—— 原始邮件 ——\n发件人：${selected.from}\n主题：${detail?.subject || selected.subject}\n\n${detail?.body || selected.body_preview || ''}`,
            accountId: selected.accountId,
          })}><Reply size={15} /></button>
          <button className="reader-action" title="全部回复" aria-label="回复全部" onClick={() => openCompose('reply', {
            to: [selected.from, detail?.to || selected.to].filter(Boolean).join(', '),
            subject: `Re: ${detail?.subject || selected.subject}`,
            body: `\n\n—— 原始邮件 ——\n发件人：${selected.from}\n主题：${detail?.subject || selected.subject}\n\n${detail?.body || selected.body_preview || ''}`,
            accountId: selected.accountId,
          })}><ReplyAll size={15} /></button>
          <button className="reader-action" title="转发" onClick={() => openCompose('forward', {
            subject: `Fwd: ${detail?.subject || selected.subject}`,
            body: `\n\n—— 转发邮件 ——\n发件人：${selected.from}\n主题：${detail?.subject || selected.subject}\n\n${detail?.body || selected.body_preview || ''}`,
            accountId: selected.accountId,
          })}><Forward size={15} /></button>
          <span style={{ height: 22, width: 1, background: 'var(--line-strong)', margin: '0 3px' }} />
          <button className="reader-action" title="标为已读" onClick={markCurrent}><MailOpen size={15} /></button>
          <button className="reader-action" title="归档（后端暂无归档接口）" aria-label="归档"><Archive size={15} /></button>
          <button className="reader-action" title="移到废纸篓" aria-label="移到废纸篓" onClick={async () => {
            if (!selected) return
            await api.deleteEmails({ email: selected.accountEmail, folder: selected.folder || 'inbox', items: [{ id: selected.id, folder: selected.folder, id_mode: selected.id_mode }] })
            await queryClient.invalidateQueries({ queryKey: ['emails'] })
          }}><Trash2 size={15} /></button>
          <button className="reader-action" title="标记为垃圾邮件（后端暂无移动接口）" aria-label="标记为垃圾邮件"><ShieldAlert size={15} /></button>
          <span style={{ height: 22, width: 1, background: 'var(--line-strong)', margin: '0 3px' }} />
          <button className="reader-action" title="移动到文件夹（后端暂无移动接口）" aria-label="移动到文件夹"><Folder size={15} /></button>
          <button className="reader-action" title={flaggedIds.includes(selectedKey || '') ? '取消标记' : '标记邮件'} aria-label="标记邮件" onClick={() => selectedKey && toggleFlag(selectedKey)}><Flag size={15} /></button>
        </div>
      </div>
      <div className="reader-scroll">
        <div className="message-paper">
          <div className="detail-subject">{detail?.subject || selected.subject}</div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            <strong>{detail?.from || selected.from}</strong>
            <span style={{ color: 'var(--muted)' }}> · {detail?.date || selected.date}</span>
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 16 }}>
            收件人：{detail?.to || selected.to || accounts.find((a) => a.email === selected.accountEmail)?.email || selected.accountEmail}
          </div>
          {detailQuery.isLoading && <div style={{ color: 'var(--muted)' }}>正在加载正文…</div>}
          {detailQuery.error && <div style={{ color: 'var(--red)' }}>{String((detailQuery.error as Error).message)}</div>}
          {html ? (
            <div className="email-body" dangerouslySetInnerHTML={{ __html: body }} />
          ) : (
            <div className="email-body" style={{ whiteSpace: 'pre-wrap' }}>{body}</div>
          )}
          {(detail?.attachments || []).length > 0 && (
            <div className="attachment-list" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 18 }}>
              {detail!.attachments!.map((att, i) => {
                const href = att.id
                  ? api.attachmentUrl(selected.accountEmail, selected.id, att.id, selected.folder || 'inbox', selected.id_mode || '')
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
