import type { ViewState } from '../store/mailStore'

/** Title for the message list header, including the 未读/已标记 smart views. */
export function listTitle(view: ViewState, filter: 'all' | 'unread' | 'flagged'): string {
  if (view.type === 'allInbox') {
    if (filter === 'unread') return '未读邮件'
    if (filter === 'flagged') return '已标记'
    return '所有收件箱'
  }
  if (view.type === 'favorite') {
    const accPrefix = view.email ? `${view.email} · ` : ''
    if (view.category === 'inbox') {
      if (filter === 'unread') return `${accPrefix}未读邮件`
      if (filter === 'flagged') return `${accPrefix}已标记`
      return view.email ? `${view.email} · 收件箱` : '所有收件箱'
    }
    if (view.category === 'unread') {
      return view.email ? `${view.email} · 未读邮件` : '所有未读'
    }
    if (view.category === 'sent') {
      return view.email ? `${view.email} · 已发邮件` : '所有已发邮件'
    }
  }
  return `${view.email} · 收件箱`
}
