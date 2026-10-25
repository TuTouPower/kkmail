// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { useMailStore } from './mailStore'

const s = () => useMailStore.getState()

// Every navigation must close the drawer AND reset the selection/list state.
// Seed that state with dirty values so the assertions below fail if a
// navigation action ever stops resetting any of it.
const dirtyState = {
  mobileSidebarOpen: true,
  selectedKey: 'dirty-key',
  selectedIds: ['dirty-key'],
  mobileView: 'detail' as const,
  settingsOpen: true,
  listFilter: 'flagged' as const,
}

function expectNavigationReset() {
  expect(s().mobileSidebarOpen).toBe(false)
  expect(s().selectedKey).toBeNull()
  expect(s().selectedIds).toEqual([])
  expect(s().mobileView).toBe('list')
  expect(s().settingsOpen).toBe(false)
}

describe('mobile drawer closes on every navigation', () => {
  beforeEach(() => {
    useMailStore.setState({ ...dirtyState, view: { type: 'allInbox' } })
  })

  it.each(['all', 'unread', 'flagged'] as const)('smart view %s closes the drawer and sets the filter', (filter) => {
    useMailStore.setState({ view: { type: 'account', accountId: '1', email: 'a@x' } })
    s().openSmartView(filter)
    expectNavigationReset()
    expect(s().listFilter).toBe(filter)
    expect(s().view).toEqual({ type: 'allInbox' })
  })

  it('re-selecting the active smart view still closes the drawer', () => {
    s().openSmartView('unread')
    useMailStore.setState({ ...dirtyState })
    s().openSmartView('unread')
    expectNavigationReset()
    expect(s().listFilter).toBe('unread')
  })

  it('selecting an account closes the drawer', () => {
    s().setView({ type: 'account', accountId: '2', email: 'b@x' })
    expectNavigationReset()
    expect(s().view).toEqual({ type: 'account', accountId: '2', email: 'b@x' })
    expect(s().listFilter).toBe('all')
  })

  it('selecting a favorite view closes the drawer', () => {
    s().setView({ type: 'favorite', category: 'sent' })
    expectNavigationReset()
    expect(s().view).toEqual({ type: 'favorite', category: 'sent' })

    s().setView({ type: 'favorite', category: 'inbox', accountId: 'acc-1', email: 'a@x' })
    expectNavigationReset()
    expect(s().view).toEqual({ type: 'favorite', category: 'inbox', accountId: 'acc-1', email: 'a@x' })
  })

  it('clears smart-view filters when navigating to an account or folder', () => {
    s().setView({ type: 'account', accountId: '2', email: 'b@x' })
    expect(s().listFilter).toBe('all')

    s().setListFilter('unread')
    s().setView({ type: 'folder', accountId: '2', email: 'b@x', folderId: 'folder-1', folderName: 'Archive' })
    expect(s().listFilter).toBe('all')
  })
})
