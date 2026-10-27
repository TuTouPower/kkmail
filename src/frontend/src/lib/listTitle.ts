import type { ViewState } from '../store/mailStore'

type ListFilter = 'all' | 'unread' | 'flagged'

/**
 * Suffix reflecting the active filter for a category title. The inbox
 * categories handle the filter by renaming the title itself (below), and
 * the unread category already implies the unread filter.
 */
function filterSuffix(filter: ListFilter, category: string): string {
  if (filter === 'flagged') return ' · 已标记'
  if (filter === 'unread' && category !== 'unread') return ' · 未读'
  return ''
}

/** Title for the message list header, including the 未读/已标记 smart views. */
export function listTitle(view: ViewState, filter: ListFilter): string {
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
    let base: string
    if (view.category === 'unread') {
      base = view.email ? `${view.email} · 未读邮件` : '所有未读'
    } else if (view.category === 'sent') {
      base = view.email ? `${view.email} · 已发邮件` : '已发邮件'
    } else if (view.category === 'drafts') {
      base = view.email ? `${view.email} · 草稿箱` : '草稿箱'
    } else if (view.category === 'trash') {
      base = view.email ? `${view.email} · 废纸篓` : '废纸篓'
    } else {
      base = view.email ? `${view.email} · 垃圾邮件` : '垃圾邮件'
    }
    return base + filterSuffix(filter, view.category)
  }
  if (view.type === 'group') {
    const prefix = `${view.groupName} · `
    if (view.category === 'inbox') {
      if (filter === 'unread') return `${prefix}未读邮件`
      if (filter === 'flagged') return `${prefix}已标记`
      return `${prefix}所有收件箱`
    }
    let base: string
    if (view.category === 'unread') base = `${prefix}所有未读`
    else if (view.category === 'sent') base = `${prefix}已发邮件`
    else if (view.category === 'drafts') base = `${prefix}草稿箱`
    else if (view.category === 'trash') base = `${prefix}废纸篓`
    else base = `${prefix}垃圾邮件`
    return base + filterSuffix(filter, view.category)
  }
  if (view.type === 'folder') {
    return `${view.email} · ${view.folderName}`
  }
  return `${view.email} · 收件箱`
}
