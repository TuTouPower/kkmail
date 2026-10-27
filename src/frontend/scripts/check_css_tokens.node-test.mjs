import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  extractDeclaredTokens,
  extractReferencedTokens,
  validateCssTokens,
  validateRawHexColors,
  validateDesignDarkTokens,
} from './check_css_tokens.mjs'

const scriptsDir = dirname(fileURLToPath(import.meta.url))
const root = resolve(scriptsDir, '..')
const designMarkdown = readFileSync(resolve(root, '../../DESIGN.md'), 'utf8')
const tokensCss = readFileSync(resolve(root, 'src/design-system/tokens.css'), 'utf8')

test('extracts declared CSS variables from token CSS', () => {
  const tokens = extractDeclaredTokens(`
    :root { --primary: #0066cc; --line: #2c2c2e; }
    [data-theme='dark'] { --text: #ffffff; }
  `)
  assert.ok(tokens.has('--primary'))
  assert.ok(tokens.has('--line'))
  assert.ok(tokens.has('--text'))
  assert.ok(!tokens.has('--unknown'))
})

test('extracts CSS variable references with line numbers', () => {
  const refs = extractReferencedTokens([
    'const style = {',
    '  color: "var(--text)",',
    '  background: "var(--surface)",',
    '}',
  ].join('\n'))
  assert.deepEqual(refs, [
    { name: '--text', line: 2 },
    { name: '--surface', line: 3 },
  ])
})

test('rejects source references to undeclared CSS variables', () => {
  const result = validateCssTokens({
    'src/components/BrokenCard.tsx': [
      'export function BrokenCard() {',
      "  return <div style={{ background: 'var(--undeclared-bg)', color: 'var(--primary)' }} />",
      '}',
    ].join('\n'),
  }, ':root { --primary: #0066cc; }')
  assert.equal(result.ok, false)
  assert.deepEqual(result.errors, [
    { variable: '--undeclared-bg', file: 'src/components/BrokenCard.tsx', line: 2 },
  ])
})

test('accepts source references declared in the design-system stylesheet', () => {
  const result = validateCssTokens({
    'src/components/GoodCard.tsx': "<div style={{ color: 'var(--primary)', background: 'var(--surface)' }} />",
  }, ':root { --primary: #0066cc; --surface: #ffffff; }')
  assert.equal(result.ok, true)
  assert.deepEqual(result.errors, [])
})

test('accepts CSS variables declared in local stylesheet files', () => {
  const result = validateCssTokens({
    'src/components/Local.css': '.container { --local-padding: 12px; padding: var(--local-padding); }',
  }, ':root { --primary: #0066cc; }')
  assert.equal(result.ok, true)
  assert.deepEqual(result.errors, [])
})

test('rejects raw hex colors outside token declaration blocks', () => {
  const result = validateRawHexColors({
    'src/design-system/tokens.css': [
      ':root {',
      '  --primary: #0066CC;',
      '}',
      '.focused { color: #fff; }',
      '.fallback { color: var(--primary, #000); }',
    ].join('\n'),
    'src/components/panel.css': '.panel { color: #123456; }',
  })
  assert.deepEqual(result, {
    errors: [
      { color: '#fff', file: 'src/design-system/tokens.css', line: 4 },
      { color: '#000', file: 'src/design-system/tokens.css', line: 5 },
      { color: '#123456', file: 'src/components/panel.css', line: 1 },
    ],
    ok: false,
  })
})

test('project token CSS declares the design system essentials', () => {
  const declared = extractDeclaredTokens(tokensCss)
  for (const name of ['--primary', '--surface', '--surface-2', '--line', '--text', '--muted', '--subtle', '--accent', '--warning']) {
    assert.ok(declared.has(name), `missing ${name}`)
  }
})

test('dark design colors match shipped CSS tokens', () => {
  assert.deepEqual(validateDesignDarkTokens(designMarkdown, tokensCss), [])
})

test('dark design token gate reports value drift', () => {
  const driftedDesign = designMarkdown.replace('background-dark: "#16191A"', 'background-dark: "#000000"')
  const errors = validateDesignDarkTokens(driftedDesign, tokensCss)
  assert.ok(errors.some((error) => error.designColor === 'background-dark' && error.cssToken === '--canvas'))
})
