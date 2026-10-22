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

  // 旧测试 "restores theme and widths after rebuilding the production store" 已由 t010 规范升级替代：
  // t010 AC-001 在本地持久化偏好中增加了 accountIconMode（默认 'brand'）。
  it('restores theme, widths, and accountIconMode after rebuilding the production store (t010 AC-001)', async () => {
    const { useMailStore } = await import('../store/mailStore')
    useMailStore.getState().setTheme('light')
    useMailStore.getState().setSidebarWidth(320)
    useMailStore.getState().setListWidth(480)
    useMailStore.getState().setAccountIconMode('initials')
    useMailStore.getState().setSearch('not persisted')
    expect(JSON.parse(localStorage.getItem('mail-ui-storage')!)).toEqual({
      state: { theme: 'light', sidebarWidth: 320, listWidth: 480, accountIconMode: 'initials' }, version: 0,
    })
    vi.resetModules()
    const { useMailStore: reloaded } = await import('../store/mailStore')
    expect(reloaded).not.toBe(useMailStore)
    expect(reloaded.getState()).toMatchObject({ theme: 'light', sidebarWidth: 320, listWidth: 480, accountIconMode: 'initials', search: '' })
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
