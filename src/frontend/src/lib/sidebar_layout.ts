import type { AccountSummary } from '../api/client'
import type { GroupItem } from '../api/queries'
import type { SidebarLayoutSnapshotOut } from '../api/schemaTypes'

export function compareAccounts(a: { email: string }, b: { email: string }): number {
  const aEmail = a.email.toLowerCase()
  const bEmail = b.email.toLowerCase()
  const aDomain = aEmail.slice(aEmail.lastIndexOf('@') + 1)
  const bDomain = bEmail.slice(bEmail.lastIndexOf('@') + 1)
  return aDomain.localeCompare(bDomain, 'en', { sensitivity: 'base' }) || aEmail.localeCompare(bEmail, 'en', { sensitivity: 'base' })
}

export function orderedMembers(accounts: AccountSummary[], groupId: string) {
  const members = accounts.filter((account) => account.group_id === groupId)
  if (members.some((account) => account.group_order != null)) {
    return members.sort((a, b) => (a.group_order ?? Number.MAX_SAFE_INTEGER) - (b.group_order ?? Number.MAX_SAFE_INTEGER) || compareAccounts(a, b))
  }
  return members.sort(compareAccounts)
}

/** Group id -> ordered member account ids, for every known group (A92). */
export function buildSidebarMemberships(accounts: AccountSummary[], groups: GroupItem[]): Map<string, string[]> {
  const memberships = new Map<string, string[]>()
  for (const group of groups) memberships.set(group.id, orderedMembers(accounts, group.id).map((account) => account.id))
  return memberships
}

/**
 * The persisted layout is only usable for saving once it mirrors the
 * locally derived group/account layout exactly (A92).
 */
export function isSidebarLayoutReady(args: {
  groupsReady: boolean
  accountsReady: boolean
  layoutSnapshot: SidebarLayoutSnapshotOut | undefined
  groups: GroupItem[]
  masterIds: string[]
  ungroupedIds: string[]
  memberships: Map<string, string[]>
}): boolean {
  const { groupsReady, accountsReady, layoutSnapshot, groups, masterIds, ungroupedIds, memberships } = args
  return Boolean(
    groupsReady && accountsReady && layoutSnapshot &&
    layoutSnapshot.group_ids.length === groups.length && layoutSnapshot.group_ids.every((id, index) => id === groups[index].id) &&
    layoutSnapshot.master_account_ids.length === masterIds.length && layoutSnapshot.master_account_ids.every((id, index) => id === masterIds[index]) &&
    layoutSnapshot.ungrouped_account_ids.length === ungroupedIds.length && layoutSnapshot.ungrouped_account_ids.every((id, index) => id === ungroupedIds[index]) &&
    Object.keys(layoutSnapshot.group_account_ids).length === memberships.size &&
    [...memberships].every(([groupId, memberIds]) => {
      const snapshotMembers = layoutSnapshot.group_account_ids[groupId]
      return snapshotMembers?.length === memberIds.length && snapshotMembers.every((id, index) => id === memberIds[index])
    }),
  )
}
