import type { FavoriteCategory, ViewState } from '../store/mailStore'

export interface SyncScopePayload {
  account_id?: string
  group_id?: string
  folder_id?: string
  folder_role?: string
}

/**
 * Map a sidebar category to the folder role the backend syncs.
 * Real roles pass through verbatim; `unread` is a list filter over the inbox,
 * not a folder role, so it maps to inbox while the list keeps its filter.
 */
export function categoryToFolderRole(category: FavoriteCategory): string {
  return category === 'unread' ? 'inbox' : category
}

export function viewToSyncScope(view: ViewState): SyncScopePayload {
  // Scope kinds are mutually exclusive: a view contributes exactly one of
  // folder (exact folder_id), group, or account — never a combination, and an
  // unknown/empty scope never degrades to a global sync beyond the global
  // inbox view itself.
  if (view.type === 'folder') {
    return {
      account_id: view.accountId,
      folder_id: view.folderId,
      folder_role: view.folderRole,
    }
  }
  if (view.type === 'account') {
    return {
      account_id: view.accountId,
      folder_role: 'inbox',
    }
  }
  if (view.type === 'group') {
    return {
      group_id: view.groupId,
      folder_role: categoryToFolderRole(view.category),
    }
  }
  if (view.type === 'favorite') {
    return {
      ...(view.accountId ? { account_id: view.accountId } : {}),
      folder_role: categoryToFolderRole(view.category),
    }
  }
  // allInbox or others -> global
  return {
    folder_role: 'inbox',
  }
}
