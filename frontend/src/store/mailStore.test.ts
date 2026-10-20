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
    useMailStore.setState({ ...dirtyState, listFilter: 'all', view: { type: 'allInbox' } })
  })

  it.each(['all', 'unread', 'flagged'] as const)('smart view %s closes the drawer and sets the filter', (filter) => {
    useMailStore.setState({ view: { type: 'accountFolder', accountId: '1', email: 'a@x', folder: 'junkemail' } })
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

  it.each(['inbox', 'junkemail', 'deleteditems', 'all'])('account folder %s closes the drawer', (folder) => {
    s().setView({ type: 'accountFolder', accountId: '2', email: 'b@x', folder })
    expectNavigationReset()
    expect(s().view).toEqual({ type: 'accountFolder', accountId: '2', email: 'b@x', folder })
  })
})
