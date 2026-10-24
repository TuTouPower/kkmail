#!/usr/bin/env node
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tokensCssPath = resolve(root, 'src/design-system/tokens.css')
const designDocPath = resolve(root, '../../assets/DESIGN.md')
const srcDir = resolve(root, 'src')

const TOKEN_DECL_REGEX = /(--[a-zA-Z0-9_-]+)\s*:/g
const TOKEN_REF_REGEX = /var\(\s*(--[a-zA-Z0-9_-]+)/g
const DESIGN_DARK_TOKEN_MAP = Object.freeze({
  'background-dark': ['--canvas'],
  'sidebar-dark': ['--sidebar'],
  'list-dark': ['--list'],
  'reader-dark': ['--reader', '--mail-body'],
  'surface-dark': ['--surface'],
  'surface-container-dark': ['--surface-2'],
  'hover-dark': ['--surface-hover'],
  'selected-dark': ['--selected'],
  'text-dark': ['--text'],
  'muted-dark': ['--muted'],
  'subtle-dark': ['--subtle'],
  'border-dark': ['--line', '--line-strong'],
  'icons-dark': ['--icon'],
  'icons-hover-dark': ['--icon-hover'],
  'danger-dark': ['--danger', '--red'],
})

function extractDeclared(css) {
  const set = new Set()
  TOKEN_DECL_REGEX.lastIndex = 0
  let match
  while ((match = TOKEN_DECL_REGEX.exec(css)) !== null) {
    set.add(match[1])
  }
  return set
}

function extractReferenced(content) {
  const refs = []
  const lines = content.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    TOKEN_REF_REGEX.lastIndex = 0
    let match
    while ((match = TOKEN_REF_REGEX.exec(line)) !== null) {
      refs.push({ name: match[1], line: i + 1 })
    }
  }
  return refs
}

function extractDesignColors(markdown) {
  const frontmatter = markdown.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1]
  const colorsBlock = frontmatter?.match(/^colors:\s*\r?\n((?: {2}[^\r\n]*(?:\r?\n|$))+)/m)?.[1]
  const colors = new Map()
  if (!colorsBlock) return colors

  for (const line of colorsBlock.split(/\r?\n/)) {
    const entry = line.match(/^ {2}([\w-]+):\s*["']?(#[\da-fA-F]{3,8})["']?\s*$/)
    if (entry) colors.set(entry[1], entry[2].toUpperCase())
  }
  return colors
}

function extractDarkThemeColors(css) {
  const block = css.match(/html\[data-theme="dark"\]\s*\{([^}]*)\}/)?.[1]
  const colors = new Map()
  if (!block) return colors

  for (const entry of block.matchAll(/(--[a-zA-Z0-9_-]+)\s*:\s*(#[\da-fA-F]{3,8})\s*;/g)) {
    colors.set(entry[1], entry[2].toUpperCase())
  }
  return colors
}

export function validateDesignDarkTokens(designMarkdown, tokensCss) {
  const designColors = extractDesignColors(designMarkdown)
  const darkThemeColors = extractDarkThemeColors(tokensCss)
  const errors = []

  for (const [designColor, cssTokens] of Object.entries(DESIGN_DARK_TOKEN_MAP)) {
    const designValue = designColors.get(designColor)
    if (!designValue) {
      errors.push({ designColor, message: 'missing color in assets/DESIGN.md' })
      continue
    }

    for (const cssToken of cssTokens) {
      const cssValue = darkThemeColors.get(cssToken)
      if (!cssValue) {
        errors.push({ designColor, cssToken, designValue, message: 'missing dark theme token' })
      } else if (designValue !== cssValue) {
        errors.push({ designColor, cssToken, designValue, cssValue, message: 'value differs' })
      }
    }
  }

  return errors
}

function walk(dir) {
  let files = []
  for (const item of readdirSync(dir)) {
    if (item === 'node_modules' || item === 'dist' || item === 'generated' || item.startsWith('.')) {
      continue
    }
    const full = join(dir, item)
    const st = statSync(full)
    if (st.isDirectory()) {
      files = files.concat(walk(full))
    } else if (/\.(css|tsx|ts|jsx|js)$/.test(item) && !item.endsWith('.test.ts') && !item.endsWith('.test.tsx')) {
      files.push(full)
    }
  }
  return files
}

function runChecks() {
  const tokensCss = readFileSync(tokensCssPath, 'utf8')
  const declared = extractDeclared(tokensCss)

  const allFiles = walk(srcDir)
  // Collect local declarations in CSS
  for (const f of allFiles) {
    if (f.endsWith('.css')) {
      const css = readFileSync(f, 'utf8')
      for (const d of extractDeclared(css)) declared.add(d)
    }
  }

  const errors = []
  for (const f of allFiles) {
    const content = readFileSync(f, 'utf8')
    const refs = extractReferenced(content)
    const rel = relative(root, f)
    for (const r of refs) {
      if (!declared.has(r.name)) {
        errors.push({ file: rel, line: r.line, variable: r.name })
      }
    }
  }

  const designMarkdown = readFileSync(designDocPath, 'utf8')
  const designTokenErrors = validateDesignDarkTokens(designMarkdown, tokensCss)

  if (errors.length > 0) {
    console.error(`❌ Found ${errors.length} undeclared CSS variable reference(s):`)
    for (const e of errors) {
      console.error(`  - ${e.file}:${e.line} -> ${e.variable}`)
    }
  } else {
    console.log('✅ All CSS variable references in frontend are declared.')
  }

  if (designTokenErrors.length > 0) {
    console.error(`❌ Found ${designTokenErrors.length} dark design token mismatch(es):`)
    for (const e of designTokenErrors) {
      const actual = e.cssValue ? `, tokens.css=${e.cssValue}` : ''
      console.error(`  - ${e.designColor}${e.cssToken ? ` (${e.cssToken})` : ''}: DESIGN.md=${e.designValue ?? 'missing'}${actual}; ${e.message}`)
    }
  } else {
    console.log('✅ Dark design colors in DESIGN.md match tokens.css.')
  }

  if (errors.length > 0 || designTokenErrors.length > 0) process.exitCode = 1
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runChecks()
}
