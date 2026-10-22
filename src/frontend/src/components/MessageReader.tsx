import { memo, useMemo, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Mail, MailOpen, Trash2, Flag, ArrowLeft } from 'lucide-react'
import { fetchAccounts, findCachedMail, flagOptimistic, setReadOptimistic, queryClient, queryKeys, removeCachedMail } from '../api/queries'
import { fetchMailCoreMessage, mailCoreAttachmentUrl, mailCoreToMailDetail, postMailCoreMessageTrash } from '../api/mailCore'
import { mailKey } from '../lib/mailKey'
import { useMailStore } from '../store/mailStore'
import { confirmAction, errorMessage } from '../lib/actions'
import { MAIL_IFRAME_SANDBOX, buildMailSrcdoc, classifyMailHtml, isHtmlBody } from '../lib/mailBody'
import { formatReaderDate } from '../lib/listDate'
import { displayEmail, displayName } from '../lib/displayName'
import { formatFileSize } from '../lib/formatSize'
import { resolveTheme } from '../lib/theme'

const MessageReader = memo(function MessageReader() {
  const themePref = useMailStore((s) => s.theme)
  const resolvedTheme = resolveTheme(themePref)
  const selectedKey = useMailStore((s) => s.selectedKey)
  const setSelectedKey = useMailStore((s) => s.setSelectedKey)
  const setMobileView = useMailStore((s) => s.setMobileView)
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []
  const [actionStatus, setActionStatus] = useState('')
  const [allowedRemoteImagesKey, setAllowedRemoteImagesKey] = useState<string | null>(null)
  const loadRemoteImages = Boolean(selectedKey && allowedRemoteImagesKey === selectedKey)

  // Re-render when mail-core list caches change (optimistic flag/read/delete), not the whole query cache.
  const selectedSnap = useSyncExternalStore(
    (cb) =>
      queryClient.getQueryCache().subscribe((event) => {
        const qk = event?.query?.queryKey
        if (Array.isArray(qk) && qk[0] === 'mail-core') cb()
      }),
    () => {
      const m = findCachedMail(selectedKey)
      return m ? `${m.id}\0${m.is_flagged ? 1 : 0}\0${m.is_read ? 1 : 0}\0${m.subject}` : ''
    },
  )
  void selectedSnap
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

  const detail = detailQuery.data
  const body = detail?.body || selected?.body_preview || ''
  const html = Boolean(detail?.body && isHtmlBody(detail.body_type))
  const currentMailKey = selected ? mailKey(selected) : undefined
  const mailThemeClass = useMemo(() => (html ? classifyMailHtml(body) : 'plain'), [html, body])
  const mailSrcdoc = useMemo(
    () => (body ? buildMailSrcdoc(body, { loadRemoteImages, theme: resolvedTheme }) : ''),
    [body, loadRemoteImages, resolvedTheme],
  )

  if (!selected) {
    return (
      <section className="reader-pane" aria-label="邮件正文">
        <div className="reader-toolbar"><div className="reader-location">未选择邮件</div></div>
        <div className="reader-scroll">
          <div data-ui="MR10" className="no-message">
            <strong>未选择邮件</strong>
            <span>从邮件列表中选择一封邮件以查看内容。</span>
          </div>
        </div>
      </section>
    )
  }

  async function toggleReadCurrent() {
    if (!selected) return
    try {
      await setReadOptimistic([selected], !selected.is_read)
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
      setSelectedKey(null)
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
      <div data-ui="MR01" className="reader-toolbar">
        <button className="reader-action mobile-only" title="返回列表" aria-label="返回列表" onClick={() => setMobileView('list')}><ArrowLeft size={18} /></button>
        <div className="reader-location">{selected.accountEmail}</div>
        <div className="reader-toolbar-actions">
          <button
            data-ui="MR02"
            className="reader-action"
            title={selected.is_read ? '标为未读' : '标为已读'}
            aria-label={selected.is_read ? '标为未读' : '标为已读'}
            onClick={toggleReadCurrent}
          >
            {selected.is_read ? <Mail size={18} /> : <MailOpen size={18} />}
          </button>
          <button data-ui="MR04" className="reader-action" title="移到废纸篓（删除）" aria-label="移到废纸篓（删除）" onClick={trashCurrent}><Trash2 size={18} /></button>
          <button
            data-ui="MR03"
            className="reader-action"
            title={selected.is_flagged ? '取消标记' : '标记邮件'}
            aria-label={selected.is_flagged ? '取消标记' : '标记邮件'}
            aria-pressed={selected.is_flagged}
            onClick={toggleFlagged}
          ><Flag size={18} /></button>
        </div>
      </div>
      <div className="reader-scroll">
        <div data-ui="MR08" className="message-paper">
          <div data-ui="MR05" className="detail-subject">{detail?.subject || selected.subject}</div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            <strong data-ui="MR06">{displayName(detail?.from || selected.from)}</strong>
            <span style={{ color: 'var(--muted)' }}> · {formatReaderDate(detail?.date || selected.date)}</span>
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 4, overflowWrap: 'anywhere' }}>
            发件人：{displayEmail(detail?.from || selected.from)}
          </div>
          <div data-ui="MR07" style={{ color: 'var(--muted)', fontSize: 11, marginBottom: detail?.cc ? 4 : 16, overflowWrap: 'anywhere' }}>
            收件人：{detail?.to || selected.to || accounts.find((a) => a.email === selected.accountEmail)?.email || selected.accountEmail}
          </div>
          {detail?.cc && (
            <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 16, overflowWrap: 'anywhere' }}>抄送：{detail.cc}</div>
          )}
          {actionStatus && <div role="status" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 8 }}>{actionStatus}</div>}
          {detailQuery.isLoading && <div style={{ color: 'var(--muted)' }}>正在加载正文…</div>}
          {detailQuery.error && <div style={{ color: 'var(--red)' }}>{String((detailQuery.error as Error).message)}</div>}
          {detail?.parse_error && (
            <div
              data-ui="MR-PARSE-ERROR"
              role="alert"
              className="parse-error-placeholder"
              style={{
                padding: '16px',
                textAlign: 'center',
                color: 'var(--red)',
                background: 'var(--surface-2)',
                borderRadius: 8,
                fontSize: 13,
                marginBottom: 16,
                border: '1px solid var(--line)',
              }}
            >
              <p style={{ margin: '0 0 8px 0', fontWeight: 600 }}>邮件解析失败</p>
              <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)', overflowWrap: 'anywhere' }}>{detail.parse_error}</p>
            </div>
          )}
          {!detail?.parse_error && !body && !detailQuery.isLoading ? (
            <div className="empty-body-placeholder" style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--muted)', background: 'var(--surface-2)', borderRadius: 8, fontSize: 13 }}>
              <p style={{ margin: '0 0 8px 0', fontWeight: 600 }}>邮件正文尚未完成同步或内容为空</p>
              <p style={{ margin: 0, fontSize: 12 }}>该邮件目前仅同步了元数据摘要。后台归档任务将自动排队拉取完整原文。</p>
            </div>
          ) : html ? (
            <>
              {!loadRemoteImages && /<img\b[^>]+src\s*=\s*["']https?:/i.test(body) && (
                <div style={{ fontSize: 12, marginBottom: 10, padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 8, background: 'var(--surface-2)', color: 'var(--text)' }}>
                  远程图片已拦截（防追踪）。
                  <button
                    type="button"
                    style={{
                      marginLeft: 8,
                      padding: '3px 8px',
                      borderRadius: 4,
                      border: '1px solid var(--line)',
                      background: 'var(--surface)',
                      color: 'var(--text)',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                    onClick={() => selectedKey && setAllowedRemoteImagesKey(selectedKey)}
                  >
                    仅此邮件允许加载
                  </button>
                </div>
              )}
              {resolvedTheme === 'dark' && mailThemeClass === 'light' ? (
                <div
                  className="mail-paper-card"
                  style={{
                    background: '#FFFFFF',
                    borderRadius: 8,
                    padding: '16px',
                    boxSizing: 'border-box',
                    boxShadow: '0 4px 16px rgba(0, 0, 0, 0.28)',
                  }}
                >
                  <iframe
                    key={`${currentMailKey}-${resolvedTheme}`}
                    className="email-body email-body-frame"
                    title="邮件正文"
                    sandbox={MAIL_IFRAME_SANDBOX}
                    referrerPolicy="no-referrer"
                    srcDoc={mailSrcdoc}
                    style={{ width: '100%', minHeight: 420, border: 0, background: '#FFFFFF', borderRadius: 6, display: 'block' }}
                  />
                </div>
              ) : (
                <iframe
                  key={`${currentMailKey}-${resolvedTheme}`}
                  className="email-body email-body-frame"
                  title="邮件正文"
                  sandbox={MAIL_IFRAME_SANDBOX}
                  referrerPolicy="no-referrer"
                  srcDoc={mailSrcdoc}
                  style={{
                    width: '100%',
                    minHeight: 420,
                    border: 0,
                    background: resolvedTheme === 'dark' ? '#1A1A1C' : '#FFFFFF',
                    borderRadius: 8,
                    display: 'block',
                  }}
                />
              )}
            </>
          ) : (
            <div className="email-body email-body-text">{body}</div>
          )}
          {(detail?.attachments || []).length > 0 && (
            <div data-ui="MR09" className="attachment-list" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 18 }}>
              {detail!.attachments!.map((att, i) => {
                const href = att.id ? mailCoreAttachmentUrl(att.id) : undefined
                return (
                  <a
                    key={att.id || i}
                    href={href}
                    download={att.name || true}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 9, color: 'inherit', textDecoration: 'none' }}
                  >
                    <strong>{att.name || '附件'}</strong>
                    {att.size ? <small style={{ display: 'block', color: 'var(--muted)' }}>{formatFileSize(att.size)}</small> : null}
                  </a>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  )
})

export default MessageReader
