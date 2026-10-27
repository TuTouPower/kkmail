import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Mail, MailOpen, Trash2, Flag, ArrowLeft, RefreshCw } from 'lucide-react'
import { findCachedMail, flagOptimistic, invalidateMailListQueries, invalidateMailStatsQueries, isMailListQueryKey, setReadOptimistic, queryClient, removeCachedMail, type MailItem } from '../api/queries'
import { fetchMailCoreMessage, mailCoreAttachmentUrl, mailCoreToMailDetail, postMailCoreMessageTrash, postMailCoreSyncMessageBody } from '../api/mailCore'
import { mailKey } from '../lib/mailKey'
import { useMailStore } from '../store/mailStore'
import { confirmAction, errorMessage } from '../lib/actions'
import { MAIL_IFRAME_SANDBOX, buildMailSrcdoc, isHtmlBody, prepareMailHtml } from '../lib/mailBody'
import { formatReaderDate } from '../lib/listDate'
import { displayEmail, displayName } from '../lib/displayName'
import { formatFileSize } from '../lib/formatSize'
import { resolveTheme } from '../lib/theme'
import { logDiagnostic } from '../lib/diagnostics'
import CopyAddress from './CopyAddress'

type RecipientAddress = { name: string | null; address: string | null; text?: string | null }

function formatRecipientName(name: string): string {
  return /[",]/.test(name) ? `"${name.replace(/(["\\])/g, '\\$1')}"` : name
}

function RecipientList({ raw, addresses }: { raw?: string; addresses?: RecipientAddress[] }) {
  if (!addresses?.length) return <>{raw || ''}</>
  return <>
    {addresses.map((recipient, index) => <span key={`${recipient.address || recipient.text || recipient.name || 'recipient'}-${index}`}>
      {index > 0 ? ', ' : ''}
      {recipient.address ? <>
        {recipient.name ? `${formatRecipientName(recipient.name)} <` : ''}
        <CopyAddress address={recipient.address}>{recipient.address}</CopyAddress>
        {recipient.name ? '>' : ''}
      </> : recipient.text || recipient.name || ''}
    </span>)}
  </>
}

/**
 * F1: stable subscribe/getSnapshot for the selected-mail snapshot.
 * Previously both were inline closures: React unsubscribed/resubscribed
 * on every render, and findCachedMail (a full scan of every cached list)
 * ran several times per frame — getSnapshot is called repeatedly by
 * React and the render body scanned again for `selected`. Now the
 * subscribe identity is stable, cache events only bump a version, and
 * the scan result is memoized per (selectedKey, version) and shared by
 * getSnapshot and the render body.
 */
function useSelectedMail(selectedKey: string | null): MailItem | undefined {
  const versionRef = useRef(0)
  const memoRef = useRef<{ key: string | null; version: number; snap: string; mail: MailItem | undefined } | null>(null)
  const subscribe = useCallback((cb: () => void) => queryClient.getQueryCache().subscribe((event) => {
    if (!isMailListQueryKey(event?.query?.queryKey)) return
    versionRef.current += 1
    cb()
  }), [])
  const getSnapshot = useCallback(() => {
    const memo = memoRef.current
    if (memo && memo.key === selectedKey && memo.version === versionRef.current) return memo.snap
    const m = findCachedMail(selectedKey)
    // A123: the snapshot is the re-render signal, so it must cover every
    // field the reader renders (from/date/accountEmail/has_attachments/…),
    // not just id/is_flagged/is_read/subject. Serializing the whole row
    // keeps any current or future cached field change visible to React.
    const snap = m ? JSON.stringify(m) : ''
    memoRef.current = { key: selectedKey, version: versionRef.current, snap, mail: m }
    return snap
  }, [selectedKey])
  useSyncExternalStore(subscribe, getSnapshot)
  const memo = memoRef.current
  if (memo && memo.key === selectedKey && memo.version === versionRef.current) return memo.mail
  return findCachedMail(selectedKey)
}

const MessageReader = memo(function MessageReader() {
  const themePref = useMailStore((s) => s.theme)
  const resolvedTheme = resolveTheme(themePref)
  const selectedKey = useMailStore((s) => s.selectedKey)
  const setSelectedKey = useMailStore((s) => s.setSelectedKey)
  const setMobileView = useMailStore((s) => s.setMobileView)
  const [actionStatus, setActionStatus] = useState('')
  const [allowedRemoteImagesKey, setAllowedRemoteImagesKey] = useState<string | null>(null)
  const loadRemoteImages = Boolean(selectedKey && allowedRemoteImagesKey === selectedKey)

  // Re-render when the selected mail's cached fields change (optimistic
  // flag/read/delete), not on every query-cache event.
  const selected = useSelectedMail(selectedKey)

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
  useEffect(() => {
    if (!detailQuery.error || !selected?.id) return
    logDiagnostic('error', 'api', '邮件详情加载失败', {
      message_id: selected.id,
      error: errorMessage(detailQuery.error, '未知详情错误'),
    })
  }, [detailQuery.error, selected?.id])

  const detail = detailQuery.data
  const senderDisplay = detail?.from || selected?.from || ''
  const senderAddress = detail?.fromAddress || displayEmail(senderDisplay)
  const hasCc = Boolean(detail?.cc || detail?.ccAddresses?.length)
  const body = detail?.body || ''
  const html = Boolean(detail?.body && isHtmlBody(detail.body_type))
  const currentMailKey = selected ? mailKey(selected) : undefined

  const isPendingArchive = Boolean(
    detail && !detail.parse_error && !detail.body && detail.is_archived === false,
  )
  const archiveState = detail?.archive_state
  const archiveHasError = Boolean(detail?.archive_has_error || archiveState === 'archive_failed')
  const archivePaused = archiveState === 'archive_paused_quota'
  const archiveProcessing = archiveState === 'archive_in_progress'

  // Body-submit state is bound to {message_id, request_generation}: every
  // submission gets a fresh generation and selection changes invalidate all
  // older generations, so a late result (even for an A→B→A reselection of the
  // same message) can never write state for the current selection.
  interface BodySyncState {
    messageId: string
    generation: number
    syncing: boolean
    queued: boolean
    error: string | null
  }
  const [bodySync, setBodySync] = useState<BodySyncState | null>(null)
  const bodySyncGenerationRef = useRef(0)
  const bodySyncAbortRef = useRef<AbortController | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const autoSyncedMsgIdRef = useRef<string | null>(null)

  useEffect(() => {
    selectedIdRef.current = selected?.id ?? null
  }, [selected?.id])

  // Rendering also filters by the current message: state recorded for another
  // message is invisible even before the selection-change cleanup runs.
  const currentBodySync = bodySync && selected?.id && bodySync.messageId === selected.id ? bodySync : null
  const syncingBody = currentBodySync?.syncing ?? false
  const syncQueued = currentBodySync?.queued ?? false
  const syncError = currentBodySync?.error ?? null

  const handleSyncBody = useCallback(async () => {
    if (!selected?.id || syncingBody) return
    const targetMsgId = selected.id
    const generation = ++bodySyncGenerationRef.current
    bodySyncAbortRef.current?.abort()
    const controller = new AbortController()
    bodySyncAbortRef.current = controller
    const isCurrent = () =>
      selectedIdRef.current === targetMsgId && bodySyncGenerationRef.current === generation
    setBodySync({ messageId: targetMsgId, generation, syncing: true, queued: false, error: null })
    try {
      const res = await postMailCoreSyncMessageBody(targetMsgId, controller.signal)
      if (!isCurrent()) return
      setBodySync({
        messageId: targetMsgId,
        generation,
        syncing: false,
        queued: res.status !== 'complete',
        error: null,
      })
      void queryClient.invalidateQueries({ queryKey: ['detail', 'mail-core', targetMsgId] })
    } catch (err) {
      if (controller.signal.aborted || !isCurrent()) return
      setBodySync({
        messageId: targetMsgId,
        generation,
        syncing: false,
        queued: false,
        error: errorMessage(err, '同步邮件正文失败'),
      })
    }
  }, [selected, syncingBody])

  // oxlint-disable react/set-state-in-effect -- clear request state from the previously selected message.
  useEffect(() => {
    // Invalidate every in-flight generation and cancel its network wait; a
    // request that already reached the server still completes in the
    // background, but its result is generation-checked away above.
    bodySyncGenerationRef.current += 1
    bodySyncAbortRef.current?.abort()
    bodySyncAbortRef.current = null
    setBodySync(null)
    autoSyncedMsgIdRef.current = null
  }, [selectedKey])
  // oxlint-enable react/set-state-in-effect

  useEffect(() => {
    if (
      isPendingArchive
      && !detailQuery.isLoading
      && !syncingBody
      && !syncQueued
      && !syncError
      && !archiveHasError
      && !archivePaused
      && selected?.id
    ) {
      if (autoSyncedMsgIdRef.current !== selected.id) {
        autoSyncedMsgIdRef.current = selected.id
        void handleSyncBody()
      }
    }
  }, [isPendingArchive, detailQuery.isLoading, syncingBody, syncQueued, syncError, archiveHasError, archivePaused, handleSyncBody, selected?.id])
  // A255: only HTML bodies need DOMPurify sanitization + colour
  // classification (for the iframe path); a plain-text body is rendered
  // as text and must not pay for — or be altered by — that pipeline.
  const preparedMailHtml = useMemo(() => (body && html ? prepareMailHtml(body) : null), [body, html])
  const mailThemeClass = html ? preparedMailHtml?.classification ?? 'plain' : 'plain'
  const mailSrcdoc = useMemo(
    () => (body && preparedMailHtml
      ? buildMailSrcdoc(body, {
          loadRemoteImages,
          theme: resolvedTheme,
          classification: preparedMailHtml.classification,
          preparedHtml: preparedMailHtml,
        })
      : ''),
    [body, loadRemoteImages, preparedMailHtml, resolvedTheme],
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
      await Promise.all([invalidateMailListQueries(), invalidateMailStatsQueries()])
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
        <div className="reader-location"><CopyAddress address={selected.accountEmail}>{selected.accountEmail}</CopyAddress></div>
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
            aria-pressed={selected.is_flagged ?? 'mixed'}
            onClick={toggleFlagged}
          ><Flag size={18} /></button>
        </div>
      </div>
      <div className="reader-scroll">
        <div data-ui="MR08" className="message-paper">
          <div data-ui="MR05" className="detail-subject">{detail?.subject || selected.subject}</div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            <strong data-ui="MR06">{displayName(senderDisplay)}</strong>
            <span style={{ color: 'var(--muted)' }}> · {formatReaderDate(detail ? detail.date : selected.date)}</span>
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 4, overflowWrap: 'anywhere' }}>
            {senderAddress ? <>发件人：<CopyAddress address={senderAddress}>{senderAddress}</CopyAddress></> : ''}
          </div>
          {detail && (
            <div data-ui="MR07" style={{ color: 'var(--muted)', fontSize: 11, marginBottom: hasCc ? 4 : 16, overflowWrap: 'anywhere' }}>
              收件人：<RecipientList raw={detail.to} addresses={detail.toAddresses} />
            </div>
          )}
          {hasCc && detail && (
            <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 16, overflowWrap: 'anywhere' }}>抄送：<RecipientList raw={detail.cc} addresses={detail.ccAddresses} /></div>
          )}
          {actionStatus && <div role="status" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 8 }}>{actionStatus}</div>}
          {detailQuery.isLoading ? (
            <div style={{ color: 'var(--muted)' }}>正在加载正文…</div>
          ) : detailQuery.error ? (
            <div role="alert" style={{ color: 'var(--red)' }}>邮件正文加载失败，请稍后重试。</div>
          ) : (
            <>
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
                    marginBottom: body ? 16 : 0,
                    border: '1px solid var(--line)',
                  }}
                >
                  <p style={{ margin: '0 0 8px 0', fontWeight: 600 }}>邮件解析失败</p>
                  <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)', overflowWrap: 'anywhere' }}>{detail.parse_error}</p>
                </div>
              )}
              {!body && !detail?.parse_error && detail?.is_archived === false ? (
            <div
              className="empty-body-placeholder"
              style={{
                padding: '32px 16px',
                textAlign: 'center',
                color: 'var(--muted)',
                background: 'var(--surface-2)',
                borderRadius: 8,
                fontSize: 13,
              }}
            >
              {syncingBody ? (
                <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                  <RefreshCw size={18} className="spin" style={{ color: 'var(--primary)' }} />
                  <p style={{ margin: 0, fontWeight: 600, color: 'var(--text)' }}>正在提交正文同步任务…</p>
                  <p style={{ margin: 0, fontSize: 12 }}>任务提交后由后台归档 Worker 拉取完整原文。</p>
                </div>
              ) : syncError ? (
                <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <p style={{ margin: 0, fontWeight: 600, color: 'var(--red)' }}>{syncError}</p>
                  <button
                    type="button"
                    onClick={handleSyncBody}
                    style={{
                      marginTop: 4,
                      padding: '4px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--line)',
                      background: 'var(--surface)',
                      color: 'var(--text)',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                  >
                    立即重试同步
                  </button>
                </div>
              ) : archiveHasError ? (
                <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <p role="alert" style={{ margin: 0, fontWeight: 600, color: 'var(--red)' }}>正文同步失败</p>
                  <p style={{ margin: 0, fontSize: 12 }}>后台未能完成正文归档，可重新提交任务。</p>
                  <button
                    type="button"
                    onClick={handleSyncBody}
                    style={{
                      marginTop: 4,
                      padding: '4px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--line)',
                      background: 'var(--surface)',
                      color: 'var(--text)',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                  >
                    立即重试同步
                  </button>
                </div>
              ) : archivePaused ? (
                <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <p style={{ margin: 0, fontWeight: 600 }}>正文同步因存储配额暂停</p>
                  <p style={{ margin: 0, fontSize: 12 }}>释放存储空间后，后台任务会继续处理。</p>
                </div>
              ) : syncQueued || archiveProcessing || archiveState === 'archive_pending' ? (
                <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                  <RefreshCw size={18} className="spin" style={{ color: 'var(--primary)' }} />
                  <p style={{ margin: 0, fontWeight: 600, color: 'var(--text)' }}>
                    {archiveProcessing ? '后台正在同步邮件正文…' : '正文同步任务已排队'}
                  </p>
                  <p style={{ margin: 0, fontSize: 12 }}>后台归档 Worker 将拉取并保存完整原文。</p>
                </div>
              ) : isPendingArchive ? (
                <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                  <p style={{ margin: '0 0 8px 0', fontWeight: 600 }}>邮件正文尚未完成同步</p>
                  <p style={{ margin: '0 0 12px 0', fontSize: 12 }}>该邮件目前仅同步了元数据摘要。后台归档任务将自动排队拉取完整原文。</p>
                  <button
                    type="button"
                    onClick={handleSyncBody}
                    style={{
                      padding: '4px 12px',
                      borderRadius: 6,
                      border: '1px solid var(--line)',
                      background: 'var(--surface)',
                      color: 'var(--text)',
                      cursor: 'pointer',
                      fontSize: 12,
                    }}
                  >
                    立即拉取正文
                  </button>
                </div>
              ) : (
                <p style={{ margin: 0, fontWeight: 600 }}>邮件正文尚未完成同步</p>
              )}
            </div>
          ) : html ? (
            <>
              {/* A277: judge remote images on the SANITIZED html, not the raw
                  body — markup that sanitization strips (e.g. inside a
                  script) must not trigger the banner, and an unquoted
                  src= must still be recognised. */}
              {!loadRemoteImages && preparedMailHtml && /<img\b[^>]*?\ssrc\s*=\s*["']?https?:\/\//i.test(preparedMailHtml.sanitizedHtml) && (
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
                    background: resolvedTheme === 'dark' ? '#222729' : '#FFFFFF',
                    borderRadius: 8,
                    display: 'block',
                  }}
                />
              )}
            </>
          ) : body ? (
            <div className="email-body email-body-text">{body}</div>
          ) : null}
            </>
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
