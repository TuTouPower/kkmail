import { beforeEach, describe, expect, it } from 'vitest'
import { useMailStore } from './mailStore'

describe('theme + settings page', () => {
  beforeEach(() => {
    useMailStore.setState({ theme: 'dark', settingsOpen: false })
  })
  it('supports follow-system theme', () => {
    useMailStore.getState().setTheme('system')
    expect(useMailStore.getState().theme).toBe('system')
  })
  it('opens settings as a page and closes on mail navigation', () => {
    useMailStore.getState().openSettings()
    expect(useMailStore.getState().settingsOpen).toBe(true)
    useMailStore.getState().setView({ type: 'allInbox' })
    expect(useMailStore.getState().settingsOpen).toBe(false)
  })
  it('clamps column widths', () => {
    useMailStore.getState().setSidebarWidth(50)
    expect(useMailStore.getState().sidebarWidth).toBe(180)
    useMailStore.getState().setListWidth(9999)
    expect(useMailStore.getState().listWidth).toBe(560)
  })
})
