import { Reply, ReplyAll, Forward, MailOpen, Archive, Trash2, Flag, Folder, MoreHorizontal } from 'lucide-react'
import { useMailStore } from '../store/mailStore'

export default function MessageReader() {
  const { messages, selectedId, view, } = useMailStore()
  const m = messages.find((x) => x.id === selectedId)

  if (!m) {
    return (
      <section className="reader-pane" aria-label="邮件正文">
        <div className="reader-toolbar">
          <div className="reader-location">未选择邮件</div>
        </div>
        <div className="reader-scroll">
          <div className="no-message">
            <strong>未选择邮件</strong>
            <span>从左侧邮件列表中选择一封邮件以查看内容。</span>
          </div>
        </div>
      </section>
    )
  }

  const email = m.sender.toLowerCase().replace(/\s+/g, '.') + '@example.com'

  return (
    <section className="reader-pane" aria-label="邮件正文">
      <div className="reader-toolbar">
        <div className="reader-location">
          {view.type === 'allInbox' ? '所有收件箱' : '邮件'} · {m.accountId}
        </div>
        <div className="reader-toolbar-actions" aria-label="当前邮件操作">
          <button className="reader-action" title="回复">
            <Reply size={15} />
          </button>
          <button className="reader-action" title="回复全部">
            <ReplyAll size={15} />
          </button>
          <button className="reader-action" title="转发">
            <Forward size={15} />
          </button>
          <span style={{ height: 22, width: 1, background: 'var(--line-strong)', margin: '0 3px' }} />
          <button className="reader-action" title="标为已读 / 未读">
            <MailOpen size={15} />
          </button>
          <button className="reader-action" title="归档">
            <Archive size={15} />
          </button>
          <button className="reader-action" title="移到废纸篓">
            <Trash2 size={15} />
          </button>
          <button className="reader-action" title="标记为垃圾邮件">
            <MailOpen size={15} />
          </button>
          <span style={{ height: 22, width: 1, background: 'var(--line-strong)', margin: '0 3px' }} />
          <button className="reader-action" title="移动到文件夹">
            <Folder size={15} />
          </button>
          <button className="reader-action" title="标记邮件">
            <Flag size={15} />
          </button>
          <button className="reader-action" title="更多操作">
            <MoreHorizontal size={15} />
          </button>
        </div>
      </div>
      <div className="reader-scroll">
        <div className="message-paper">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 13, marginBottom: 22 }}>
            <div className="avatar" style={{ height: 44, width: 44, fontSize: 17, background: m.color }}>
              {m.initial}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="detail-subject">{m.subject}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', fontSize: 12 }}>
                <span style={{ fontWeight: 700 }}>{m.sender}</span>
                <span style={{ color: 'var(--muted)' }}>{"<" + email + ">"}</span>
              </div>
              <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 5 }}>收件人：{m.accountId}</div>
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
              {m.date}
              <br />
              {m.time}
            </div>
          </div>
          <div style={{ height: 1, background: 'var(--line)', margin: '20px 0 24px' }} />
          <div className="email-body" dangerouslySetInnerHTML={{ __html: m.body }} />
        </div>
      </div>
    </section>
  )
}
