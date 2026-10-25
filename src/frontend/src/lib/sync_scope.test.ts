// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { categoryToFolderRole, viewToSyncScope } from './sync_scope'
import type { FavoriteCategory } from '../store/mailStore'

const CATEGORIES: FavoriteCategory[] = ['inbox', 'unread', 'sent', 'drafts', 'trash', 'junk']
const EXPECTED_ROLE: Record<FavoriteCategory, string> = {
  inbox: 'inbox',
  unread: 'inbox', // filter view over the inbox, not a folder role
  sent: 'sent',
  drafts: 'drafts',
  trash: 'trash',
  junk: 'junk',
}

describe('categoryToFolderRole', () => {
  it.each(CATEGORIES)('maps %s verbatim except unread -> inbox', (category) => {
    expect(categoryToFolderRole(category)).toBe(EXPECTED_ROLE[category])
  })
})

describe('viewToSyncScope', () => {
  it('global inbox syncs the inbox role with no narrower scope', () => {
    expect(viewToSyncScope({ type: 'allInbox' })).toEqual({ folder_role: 'inbox' })
  })

  it('account view syncs that account inbox only', () => {
    expect(viewToSyncScope({ type: 'account', accountId: 'acc-1', email: 'a@x.test' })).toEqual({
      account_id: 'acc-1',
      folder_role: 'inbox',
    })
  })

  it.each(CATEGORIES)('group category %s passes its real folder role through', (category) => {
    const scope = viewToSyncScope({ type: 'group', groupId: 'grp-1', groupName: 'G', category })
    expect(scope).toEqual({ group_id: 'grp-1', folder_role: EXPECTED_ROLE[category] })
    // group is mutually exclusive with account/folder
    expect(scope.account_id).toBeUndefined()
    expect(scope.folder_id).toBeUndefined()
  })

  it.each(CATEGORIES)('favorite category %s passes its real folder role through', (category) => {
    const scope = viewToSyncScope({ type: 'favorite', category, accountId: 'acc-2' })
    expect(scope).toEqual({ account_id: 'acc-2', folder_role: EXPECTED_ROLE[category] })
    expect(scope.group_id).toBeUndefined()
    expect(scope.folder_id).toBeUndefined()
  })

  it('favorite without an account carries no account scope', () => {
    const scope = viewToSyncScope({ type: 'favorite', category: 'sent' })
    expect(scope).toEqual({ folder_role: 'sent' })
    expect(scope.account_id).toBeUndefined()
  })

  it('folder view uses the exact folder_id and its role verbatim', () => {
    expect(
      viewToSyncScope({
        type: 'folder',
        accountId: 'acc-1',
        email: 'a@x.test',
        folderId: 'fld-9',
        folderName: 'Archive 2024',
        folderRole: 'custom-role',
      }),
    ).toEqual({ account_id: 'acc-1', folder_id: 'fld-9', folder_role: 'custom-role' })
    expect(
      viewToSyncScope({
        type: 'folder',
        accountId: 'acc-1',
        email: 'a@x.test',
        folderId: 'fld-1',
        folderName: '已发送',
        folderRole: 'sent',
      }),
    ).toEqual({ account_id: 'acc-1', folder_id: 'fld-1', folder_role: 'sent' })
  })
})
