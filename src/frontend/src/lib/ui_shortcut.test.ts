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

  it('does not treat Ctrl and Meta as interchangeable (A332)', () => {
    const ctrlShortcut: Shortcut = { code: 'KeyU', ctrl: true, meta: false, shift: true, alt: false }
    const metaShortcut: Shortcut = { code: 'KeyU', ctrl: false, meta: true, shift: true, alt: false }
    const metaEvent = new KeyboardEvent('keydown', { code: 'KeyU', metaKey: true, shiftKey: true })
    const ctrlEvent = new KeyboardEvent('keydown', { code: 'KeyU', ctrlKey: true, shiftKey: true })
    const bothEvent = new KeyboardEvent('keydown', { code: 'KeyU', ctrlKey: true, metaKey: true, shiftKey: true })

    expect(matchesShortcut(metaEvent, metaShortcut)).toBe(true)
    expect(matchesShortcut(ctrlEvent, ctrlShortcut)).toBe(true)
    // A shortcut recorded with Ctrl must not fire on Meta, and vice versa.
    expect(matchesShortcut(metaEvent, ctrlShortcut)).toBe(false)
    expect(matchesShortcut(ctrlEvent, metaShortcut)).toBe(false)
    // Pressing both must not satisfy a shortcut that recorded only one.
    expect(matchesShortcut(bothEvent, ctrlShortcut)).toBe(false)
    expect(matchesShortcut(bothEvent, metaShortcut)).toBe(false)
  })
})
