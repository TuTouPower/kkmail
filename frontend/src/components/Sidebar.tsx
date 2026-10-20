import { useState } from 'react'
import { ChevronDown, ChevronRight, Inbox, MailOpen, Flag, FileText, Send, Settings, PanelLeft } from 'lucide-react'
import { useMailStore } from '../store/mailStore'
import SettingsModal from './SettingsModal'

const folders = [
  { id: 'important', label: '重要', icon: Flag },
  { id: 'inbox', label: '收件箱', icon: Inbox },
  { id: 'drafts', label: '草稿', icon: FileText },
  { id: 'sent', label: '已发送', icon: Send },
  { id: 'junk', label: '垃圾邮件', icon: MailOpen },
  { id: 'trash', label: '废纸篓', icon: MailOpen },
  { id: 'archive', label: '归档', icon: MailOpen },
]

const groupNames = ['个人邮箱', '工作邮箱', '其他邮箱']

export default function Sidebar() {
  const {
    accounts,
    messages,
    view,
    setView,
    collapsedGroups,
    toggleGroup,
    collapsedAccounts,
    toggleAccount,
    toggleSidebar,
  } = useMailStore()
  const [settingsOpen, setSettingsOpen] = useState(false)

  const allInboxUnread = messages.filter((m) => m.folder === 'inbox' && m.unread).length
  const unreadCount = messages.filter((m) => m.unread).length
  const flaggedCount = messages.filter((m) => m.flagged).length

  return (
    <aside className="sidebar" aria-label="邮箱导航">
      <div className="sidebar-head">
        <button className="sidebar-toggle" onClick={toggleSidebar} title="折叠侧边栏" aria-label="折叠或展开侧边栏">
          <PanelLeft size={18} />
        </button>
      </div>
      <div className="sidebar-scroll">
        <div className="side-section">
          <div className="section-label">
            <span>个人收藏</span>
          </div>
          <button className={`side-item ${view.type === 'allInbox' ? 'active' : ''}`} onClick={() => setView({ type: 'allInbox' })}>
            <Inbox size={17} />
            <span className="side-name">所有收件箱</span>
            {allInboxUnread > 0 && <span className="side-count">{allInboxUnread}</span>}
          </button>
          <button className={`side-item ${view.type === 'unread' ? 'active' : ''}`} onClick={() => setView({ type: 'unread' })}>
            <MailOpen size={17} />
            <span className="side-name">未读邮件</span>
            {unreadCount > 0 && <span className="side-count">{unreadCount}</span>}
          </button>
          <button className={`side-item ${view.type === 'flagged' ? 'active' : ''}`} onClick={() => setView({ type: 'flagged' })}>
            <Flag size={17} />
            <span className="side-name">已标记</span>
            {flaggedCount > 0 && <span className="side-count">{flaggedCount}</span>}
          </button>
          <button className={`side-item ${view.type === 'allDrafts' ? 'active' : ''}`} onClick={() => setView({ type: 'allDrafts' })}>
            <FileText size={17} />
            <span className="side-name">所有草稿</span>
          </button>
          <button className={`side-item ${view.type === 'allSent' ? 'active' : ''}`} onClick={() => setView({ type: 'allSent' })}>
            <Send size={17} />
            <span className="side-name">所有已发送邮件</span>
          </button>
        </div>

        <div className="side-section">
          <div className="section-label">
            <span>邮箱账户</span>
          </div>
          {groupNames.map((group) => {
            const members = accounts.filter((a) => a.group === group)
            const collapsed = collapsedGroups.has(group)
            return (
              <div className="account-group" key={group}>
                <div className="account-group-head">
                  <button className="group-toggle" onClick={() => toggleGroup(group)} title={collapsed ? '展开' : '折叠'}>
                    {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                  </button>
                  <span className="group-name">{group}</span>
                  <span className="group-count">{members.length}</span>
                </div>
                {!collapsed &&
                  members.map((a) => {
                    const isCollapsed = collapsedAccounts.has(a.id)
                    const accountSelected = view.type === 'accountFolder' && view.accountId === a.id && view.folder === 'inbox'
                    const unread = messages.filter((m) => m.accountId === a.id && m.folder === 'inbox' && m.unread).length
                    return (
                      <div key={a.id}>
                        <div className="account-row">
                          <button className="account-expand" onClick={() => toggleAccount(a.id)} aria-label={isCollapsed ? '展开' : '折叠'}>
                            {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                          </button>
                          <button
                            className={`account-button ${accountSelected ? 'active' : ''}`}
                            onClick={() => setView({ type: 'accountFolder', accountId: a.id, folder: 'inbox' })}
                            title={a.email}
                          >
                            <span className="account-dot" style={{ background: a.color }}>
                              {a.provider === '网易 163' ? '163' : a.provider === 'Outlook' ? 'O' : 'G'}
                            </span>
                            <span className="account-email">{a.email}</span>
                            {unread > 0 && <span className="account-unread">{unread}</span>}
                          </button>
                        </div>
                        {!isCollapsed && (
                          <div className="folder-tree">
                            {folders.map((f) => {
                              const active = view.type === 'accountFolder' && view.accountId === a.id && view.folder === f.id
                              const Icon = f.icon
                              return (
                                <button
                                  key={f.id}
                                  className={`side-item ${active ? 'active' : ''}`}
                                  onClick={() => setView({ type: 'accountFolder', accountId: a.id, folder: f.id })}
                                >
                                  <Icon size={15} />
                                  <span className="side-name">{f.label}</span>
                                </button>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
              </div>
            )
          })}
        </div>
        <div style={{ padding: '5px 9px 4px', color: 'var(--muted)', fontSize: 10, lineHeight: 1.6 }}>
          演示数据仅保存在当前页面。<br />
          账户接入、同步与发送尚未连接真实服务。
        </div>
      </div>
      <div className="sidebar-footer">
        <button className="footer-btn" onClick={() => setSettingsOpen(true)}>
          <Settings size={17} />
          <span>设置</span>
        </button>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </aside>
  )
}
