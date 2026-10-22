#!/usr/bin/env node
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tokensCssPath = resolve(root, 'src/design-system/tokens.css')
const srcDir = resolve(root, 'src')

const TOKEN_DECL_REGEX = /(--[a-zA-Z0-9_-]+)\s*:/g
const TOKEN_REF_REGEX = /var\(\s*(--[a-zA-Z0-9_-]+)/g

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

if (errors.length > 0) {
  console.error(`❌ Found ${errors.length} undeclared CSS variable reference(s):`)
  for (const e of errors) {
    console.error(`  - ${e.file}:${e.line} -> ${e.variable}`)
  }
  process.exit(1)
} else {
  console.log('✅ All CSS variable references in frontend are declared.')
}
