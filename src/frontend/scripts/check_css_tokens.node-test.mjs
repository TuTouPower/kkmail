import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { validateDesignDarkTokens } from './check_css_tokens.mjs'

const scriptsDir = dirname(fileURLToPath(import.meta.url))
const root = resolve(scriptsDir, '..')
const designMarkdown = readFileSync(resolve(root, '../../assets/DESIGN.md'), 'utf8')
const tokensCss = readFileSync(resolve(root, 'src/design-system/tokens.css'), 'utf8')

test('dark design colors match shipped CSS tokens', () => {
  assert.deepEqual(validateDesignDarkTokens(designMarkdown, tokensCss), [])
})

test('dark design token gate reports value drift', () => {
  const driftedDesign = designMarkdown.replace('background-dark: "#16191A"', 'background-dark: "#000000"')
  const errors = validateDesignDarkTokens(driftedDesign, tokensCss)
  assert.ok(errors.some((error) => error.designColor === 'background-dark' && error.cssToken === '--canvas'))
})
