import { describe, expect, it } from 'vitest'
import { ALL_ACCOUNTS, accountScope, queryKeys } from './queries'

describe('accountScope / list query keys', () => {
  it('uses a reserved sentinel that cannot collide with account id "all"', () => {
    expect(ALL_ACCOUNTS).toBe('__all__')
    expect(accountScope(undefined)).toBe(ALL_ACCOUNTS)
    expect(accountScope('')).toBe(ALL_ACCOUNTS)
    expect(accountScope('all')).toBe('all') // real id "all" stays distinct from unified scope
    expect(queryKeys.inbox()).toEqual(['mail-core', 'inbox', ALL_ACCOUNTS])
    expect(queryKeys.inbox('all')).toEqual(['mail-core', 'inbox', 'all'])
    expect(queryKeys.inbox()).not.toEqual(queryKeys.inbox('all'))
  })

  it('registers the settings query in the central queryKeys registry (A257)', () => {
    expect(queryKeys.settings).toEqual(['settings'])
  })

  it('isolates a group scope from both global and single-account inbox caches', () => {
    expect(queryKeys.inbox(ALL_ACCOUNTS, 'all', 'inbox', 'desc', undefined, 'group-1')).not.toEqual(queryKeys.inbox())
    expect(queryKeys.inbox('account-1', 'all', 'inbox', 'desc', undefined, 'group-1')).not.toEqual(queryKeys.inbox('account-1'))
    expect(queryKeys.search('scope', ALL_ACCOUNTS, 'group-1')).not.toEqual(queryKeys.search('scope'))
    expect(queryKeys.search('scope', 'account-1', null, 'folder-1')).not.toEqual(queryKeys.search('scope', 'account-1'))
  })
})
