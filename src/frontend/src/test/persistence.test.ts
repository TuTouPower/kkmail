import { describe, expect, it, vi } from 'vitest'

describe('browser preference persistence', () => {
  it('implements Storage read, key, remove and clear semantics', () => {
    expect(localStorage.getItem('missing')).toBeNull()
    localStorage.setItem('first', '1')
    localStorage.setItem('second', '2')
    expect(localStorage.length).toBe(2)
    expect(localStorage.key(0)).toBe('first')
    expect(localStorage.getItem('first')).toBe('1')
    localStorage.removeItem('first')
    expect(localStorage.getItem('first')).toBeNull()
    localStorage.clear()
    expect(localStorage.length).toBe(0)
    expect(localStorage.key(0)).toBeNull()
  })

  // t010 增加 accountIconMode；t027 增加侧栏分区、分组与账号展开偏好。
  it('restores display and sidebar preferences after rebuilding the production store', async () => {
    const { useMailStore } = await import('../store/mailStore')
    useMailStore.getState().setTheme('light')
    useMailStore.getState().setSidebarWidth(320)
    useMailStore.getState().setListWidth(480)
    useMailStore.getState().setAccountIconMode('initials')
    useMailStore.getState().toggleSidebarSection('allAccounts')
    useMailStore.getState().toggleSidebarGroup('group-1')
    useMailStore.getState().toggleSidebarAccount('account-1')
    useMailStore.getState().setSearch('not persisted')
    expect(JSON.parse(localStorage.getItem('mail-ui-storage')!)).toEqual({
      state: {
        theme: 'light', sidebarWidth: 320, listWidth: 480, accountIconMode: 'initials',
        sidebarSections: { allAccounts: false, accountList: true },
        expandedSidebarCategories: [],
        expandedSidebarGroups: ['group-1'], expandedSidebarAccounts: ['account-1'],
        uiReferenceEnabled: true,
        uiReferenceShortcut: null,
      },
      version: 0,
    })
    vi.resetModules()
    const { useMailStore: reloaded } = await import('../store/mailStore')
    expect(reloaded).not.toBe(useMailStore)
    expect(reloaded.getState()).toMatchObject({
      theme: 'light', sidebarWidth: 320, listWidth: 480, accountIconMode: 'initials', search: '',
      sidebarSections: { allAccounts: false, accountList: true },
      expandedSidebarGroups: ['group-1'], expandedSidebarAccounts: ['account-1'],
      expandedSidebarCategories: [],
    })
    expect(reloaded.persist.hasHydrated()).toBe(true)
  })

  it('reads old partial preferences and preserves new defaults', async () => {
    localStorage.setItem('mail-ui-storage', JSON.stringify({ state: { theme: 'system' }, version: 0 }))
    vi.resetModules()
    const { useMailStore } = await import('../store/mailStore')
    expect(useMailStore.getState()).toMatchObject({ theme: 'system', sidebarWidth: 260, listWidth: 360 })
    expect(typeof useMailStore.getState().setTheme).toBe('function')
  })

  it('reports corrupt JSON through the production hydration error path', async () => {
    const { useMailStore } = await import('../store/mailStore')
    localStorage.setItem('mail-ui-storage', '{invalid')
    const finished = vi.fn()
    useMailStore.persist.setOptions({ onRehydrateStorage: () => finished })
    await useMailStore.persist.rehydrate()
    expect(finished).toHaveBeenCalledWith(undefined, expect.any(SyntaxError))
    expect(useMailStore.persist.hasHydrated()).toBe(false)
    useMailStore.persist.setOptions({ onRehydrateStorage: undefined })
  })

  it('surfaces quota failures instead of silently disabling persistence', async () => {
    const { useMailStore } = await import('../store/mailStore')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('full', 'QuotaExceededError') })
    expect(() => useMailStore.getState().setTheme('light')).toThrow('full')
  })
})
