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
})
