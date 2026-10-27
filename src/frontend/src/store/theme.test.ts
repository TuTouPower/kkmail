import { beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { useMailStore } from './mailStore'

describe('theme + settings page', () => {
  beforeEach(() => {
    useMailStore.setState({ theme: 'dark', settingsOpen: false })
  })
  it('uses the same default theme as the first-paint bootstrap (A94)', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const storeSource = readFileSync(resolve(here, 'mailStore.ts'), 'utf8')
    const bootstrap = readFileSync(resolve(here, '../../public/theme_bootstrap.js'), 'utf8')
    // Both must default to 'system', otherwise the bootstrap paints one
    // theme and the store flips to another once React mounts.
    expect(storeSource).toMatch(/^\s+theme: 'system',$/m)
    expect(bootstrap).toContain("let preference = 'system'")
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
