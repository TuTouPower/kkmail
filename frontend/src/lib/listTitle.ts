import type { ViewState } from '../store/mailStore'

const FOLDER_LABELS: Record<string, string> = {
  inbox: '收件箱',
  junkemail: '垃圾邮件',
  deleteditems: '废纸篓',
  all: '全部',
}

/** Title for the message list header, including the 未读/已标记 smart views. */
export function listTitle(view: ViewState, filter: 'all' | 'unread' | 'flagged'): string {
  if (view.type === 'allInbox') {
    if (filter === 'unread') return '未读邮件'
    if (filter === 'flagged') return '已标记'
    return '所有收件箱'
  }
  return `${view.email} · ${FOLDER_LABELS[view.folder] || view.folder}`
}
