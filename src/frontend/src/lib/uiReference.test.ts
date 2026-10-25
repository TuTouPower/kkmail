import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  formatUiReferenceText,
  isUiReferenceShortcut,
  UI_ELEMENT_REGISTRY,
} from './uiReference'

const srcDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function componentSourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return componentSourceFiles(path)
    return /\.(tsx|jsx)$/.test(entry.name) && !entry.name.includes('.test.') ? [path] : []
  })
}

function componentUiReferenceIds(): Set<string> {
  const ids = new Set<string>()
  const attributePattern = /\bdata-ui\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^}]*)\})/g
  const stringLiteralPattern = /['"]([^'"]+)['"]/g
  for (const path of componentSourceFiles(srcDirectory)) {
    const source = readFileSync(path, 'utf8')
    for (const attribute of source.matchAll(attributePattern)) {
      if (attribute[1] !== undefined || attribute[2] !== undefined) {
        ids.add(attribute[1] ?? attribute[2] ?? '')
        continue
      }
      const expression = attribute[3] ?? ''
      const outcomes = expression.includes('?') ? expression.slice(expression.indexOf('?') + 1) : expression
      for (const match of outcomes.matchAll(stringLiteralPattern)) ids.add(match[1])
    }
  }
  return ids
}

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

  it('keeps registry keys synchronized with component data-ui references', () => {
    const activeKeys = Object.entries(UI_ELEMENT_REGISTRY)
      .filter(([_, meta]) => !meta.deprecated)
      .map(([key]) => key)
    expect(activeKeys.sort()).toEqual([...componentUiReferenceIds()].sort())
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
