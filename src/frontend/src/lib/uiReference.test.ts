import { describe, expect, it } from 'vitest'
import {
  formatUiReferenceText,
  isUiReferenceShortcut,
  UI_ELEMENT_REGISTRY,
} from './uiReference'

describe('uiReference (t011 AC-001, AC-003, AC-005, AC-007, AC-008)', () => {
  it('detects shortcut combinations across platforms and rejects repeats (AC-001)', () => {
    // Windows/Linux Ctrl + Shift + .
    expect(
      isUiReferenceShortcut({
        key: '.',
        code: 'Period',
        ctrlKey: true,
        shiftKey: true,
        metaKey: false,
        altKey: false,
        repeat: false,
      } as KeyboardEvent),
    ).toBe(true)

    // macOS Cmd + Shift + .
    expect(
      isUiReferenceShortcut({
        key: '.',
        code: 'Period',
        ctrlKey: false,
        shiftKey: true,
        metaKey: true,
        altKey: false,
        repeat: false,
      } as KeyboardEvent),
    ).toBe(true)

    // Key '>' when shift is held
    expect(
      isUiReferenceShortcut({
        key: '>',
        code: 'Period',
        ctrlKey: true,
        shiftKey: true,
        metaKey: false,
        altKey: false,
        repeat: false,
      } as KeyboardEvent),
    ).toBe(true)

    // Long press repeat rejected
    expect(
      isUiReferenceShortcut({
        key: '.',
        code: 'Period',
        ctrlKey: true,
        shiftKey: true,
        metaKey: false,
        altKey: false,
        repeat: true,
      } as KeyboardEvent),
    ).toBe(false)

    // Missing shift rejected
    expect(
      isUiReferenceShortcut({
        key: '.',
        code: 'Period',
        ctrlKey: true,
        shiftKey: false,
        metaKey: false,
        altKey: false,
        repeat: false,
      } as KeyboardEvent),
    ).toBe(false)

    // Alt key held rejected
    expect(
      isUiReferenceShortcut({
        key: '.',
        code: 'Period',
        ctrlKey: true,
        shiftKey: true,
        metaKey: false,
        altKey: true,
        repeat: false,
      } as KeyboardEvent),
    ).toBe(false)
  })

  it('formats clean reference text without runtime credentials or user content (AC-005, AC-008)', () => {
    const text = formatUiReferenceText('ML03')
    expect(text).toBe('[UI:ML03] 邮件列表 · 刷新并同步按钮')
    expect(text).not.toContain('@')
    expect(text).not.toContain('password')

    const unknown = formatUiReferenceText('XX99')
    expect(unknown).toBe('[UI:XX99] 未知区域 · 未知元素')
  })

  it('verifies partition prefixes and registry validity (AC-003, AC-007)', () => {
    const validPrefixes = new Set(['LG', 'SB', 'ML', 'MR', 'ST'])
    for (const [key, meta] of Object.entries(UI_ELEMENT_REGISTRY)) {
      expect(meta.id).toBe(key)
      const prefix = key.slice(0, 2)
      expect(validPrefixes.has(prefix)).toBe(true)
      expect(meta.region.length).toBeGreaterThan(0)
      expect(meta.description.length).toBeGreaterThan(0)
    }
  })
})
