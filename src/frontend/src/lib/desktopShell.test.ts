// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { getDesktopPlatform } from './desktopShell'

afterEach(() => {
  delete (window as Window & { kkmailDesktop?: unknown }).kkmailDesktop
  window.history.replaceState({}, '', '/')
})

describe('getDesktopPlatform', () => {
  it('does not grant desktop UI to an ordinary browser', () => {
    expect(getDesktopPlatform()).toBeNull()
  })

  it('uses the isolated Electron platform hint without URL flags', () => {
    ;(window as Window & { kkmailDesktop?: unknown }).kkmailDesktop = { platform: 'darwin' }
    window.history.replaceState({}, '', '/?shell=desktop')
    expect(getDesktopPlatform()).toBe('darwin')
  })
})
