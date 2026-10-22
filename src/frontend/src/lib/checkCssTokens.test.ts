import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  extractDeclaredTokens,
  extractReferencedTokens,
  validateCssTokens,
} from './checkCssTokens'

const __dirname = dirname(fileURLToPath(import.meta.url))
const tokensCss = readFileSync(resolve(__dirname, '../design-system/tokens.css'), 'utf8')

describe('CSS token validator', () => {
  it('extracts declared CSS variables from tokens CSS', () => {
    const css = `
      :root {
        --primary: #0066cc;
        --line: #2c2c2e;
      }
      [data-theme='dark'] {
        --text: #ffffff;
      }
    `
    const tokens = extractDeclaredTokens(css)
    expect(tokens.has('--primary')).toBe(true)
    expect(tokens.has('--line')).toBe(true)
    expect(tokens.has('--text')).toBe(true)
    expect(tokens.has('--unknown')).toBe(false)
  })

  it('extracts referenced tokens with accurate line numbers', () => {
    const code = [
      'const style = {',
      '  color: "var(--text)",',
      '  background: "var(--surface)",',
      '}',
    ].join('\n')
    const refs = extractReferencedTokens(code)
    expect(refs).toEqual([
      { name: '--text', line: 2 },
      { name: '--surface', line: 3 },
    ])
  })

  it('fails with negative fixture when referencing undeclared CSS tokens (AC-006)', () => {
    const mockTokensCss = ':root { --primary: #0066cc; }'
    const mockFiles = {
      'src/components/BrokenCard.tsx': `
        export function BrokenCard() {
          return <div style={{ background: 'var(--undeclared-bg)', color: 'var(--primary)' }} />
        }
      `,
    }

    const result = validateCssTokens(mockFiles, mockTokensCss)
    expect(result.ok).toBe(false)
    expect(result.errors).toHaveLength(1)
    expect(result.errors[0]).toEqual({
      variable: '--undeclared-bg',
      file: 'src/components/BrokenCard.tsx',
      line: 3,
    })
  })

  it('passes positive fixture when all referenced tokens are declared', () => {
    const mockTokensCss = ':root { --primary: #0066cc; --surface: #ffffff; }'
    const mockFiles = {
      'src/components/GoodCard.tsx': `
        export function GoodCard() {
          return <div style={{ background: 'var(--surface)', color: 'var(--primary)' }} />
        }
      `,
    }

    const result = validateCssTokens(mockFiles, mockTokensCss)
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
  })

  it('recognizes local CSS variable declarations as valid', () => {
    const mockTokensCss = ':root { --primary: #0066cc; }'
    const mockFiles = {
      'src/components/Local.css': `
        .container {
          --local-padding: 12px;
          padding: var(--local-padding);
        }
      `,
    }

    const result = validateCssTokens(mockFiles, mockTokensCss)
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
  })

  it('verifies that project tokensCss declares essential design tokens', () => {
    const declared = extractDeclaredTokens(tokensCss)
    expect(declared.has('--primary')).toBe(true)
    expect(declared.has('--surface')).toBe(true)
    expect(declared.has('--surface-2')).toBe(true)
    expect(declared.has('--line')).toBe(true)
    expect(declared.has('--text')).toBe(true)
    expect(declared.has('--muted')).toBe(true)
    expect(declared.has('--subtle')).toBe(true)
    expect(declared.has('--accent')).toBe(true)
    expect(declared.has('--warning')).toBe(true)
  })
})
