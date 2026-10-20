import { beforeEach, describe, expect, it } from 'vitest'
import { useMailStore } from './mailStore'

const s = () => useMailStore.getState()

describe('mobile drawer closes on every navigation', () => {
  beforeEach(() => {
    useMailStore.setState({ mobileSidebarOpen: true, listFilter: 'all', view: { type: 'allInbox' } })
  })

  it.each(['all', 'unread', 'flagged'] as const)('smart view %s closes the drawer and sets the filter', (filter) => {
    useMailStore.setState({ view: { type: 'accountFolder', accountId: 1, email: 'a@x', folder: 'junkemail' } })
    s().openSmartView(filter)
    expect(s().mobileSidebarOpen).toBe(false)
    expect(s().listFilter).toBe(filter)
    expect(s().view).toEqual({ type: 'allInbox' })
  })

  it('re-selecting the active smart view still closes the drawer', () => {
    s().openSmartView('unread')
    useMailStore.setState({ mobileSidebarOpen: true })
    s().openSmartView('unread')
    expect(s().mobileSidebarOpen).toBe(false)
  })

  it.each(['inbox', 'junkemail', 'deleteditems', 'all'])('account folder %s closes the drawer', (folder) => {
    s().setView({ type: 'accountFolder', accountId: 2, email: 'b@x', folder })
    expect(s().mobileSidebarOpen).toBe(false)
    expect(s().selectedKey).toBeNull()
  })
})
