import type { ViewState } from '../store/mailStore'

/** Title for the message list header, including the 未读/已标记 smart views. */
export function listTitle(view: ViewState, filter: 'all' | 'unread' | 'flagged'): string {
  if (view.type === 'allInbox') {
    if (filter === 'unread') return '未读邮件'
    if (filter === 'flagged') return '已标记'
    return '所有收件箱'
  }
  return `${view.email} · 收件箱`
}
