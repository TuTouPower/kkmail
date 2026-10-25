import type { ViewState } from '../store/mailStore'

export interface SyncScopePayload {
  account_id?: string
  group_id?: string
  folder_id?: string
  folder_role?: string
}

export function viewToSyncScope(view: ViewState): SyncScopePayload {
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
      folder_role: view.category === 'inbox' ? 'inbox' : undefined,
    }
  }
  if (view.type === 'favorite') {
    return {
      account_id: view.accountId,
      folder_role: view.category === 'inbox' ? 'inbox' : undefined,
    }
  }
  // allInbox or others -> global
  return {
    folder_role: 'inbox',
  }
}
