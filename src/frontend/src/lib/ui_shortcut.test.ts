import { describe, expect, it } from 'vitest'
import {
  formatShortcut,
  getDefaultShortcut,
  matchesShortcut,
  type Shortcut,
} from './ui_shortcut'

describe('ui_shortcut (p052)', () => {
  it('formats platform default shortcut cleanly', () => {
    const s = getDefaultShortcut()
    const formatted = formatShortcut(s)
    expect(formatted).toContain('Shift')
    expect(formatted).toContain('.')
  })

  it('matches keyboard event with exact modifiers and code', () => {
    const shortcut: Shortcut = {
      code: 'KeyU',
      ctrl: true,
      meta: false,
      shift: true,
      alt: false,
    }

    // Exact match
    const matchingEvent = new KeyboardEvent('keydown', {
      code: 'KeyU',
      ctrlKey: true,
      shiftKey: true,
      metaKey: false,
      altKey: false,
    })
    expect(matchesShortcut(matchingEvent, shortcut)).toBe(true)

    // Repeat event must be ignored
    const repeatEvent = new KeyboardEvent('keydown', {
      code: 'KeyU',
      ctrlKey: true,
      shiftKey: true,
      repeat: true,
    })
    expect(matchesShortcut(repeatEvent, shortcut)).toBe(false)

    // Extra altKey must not match
    const extraAlt = new KeyboardEvent('keydown', {
      code: 'KeyU',
      ctrlKey: true,
      shiftKey: true,
      altKey: true,
    })
    expect(matchesShortcut(extraAlt, shortcut)).toBe(false)
  })
})
