#!/usr/bin/env node
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const srcDir = join(root, 'src')

export function findNativeControls(files) {
  const problems = []
  for (const [file, content] of Object.entries(files)) {
    const lines = content.split(/\r?\n/)
    lines.forEach((line, index) => {
      const match = line.match(/<\s*(select|datalist)\b/)
      if (match) problems.push({ file, line: index + 1, tag: match[1].toLowerCase() })
    })
  }
  return problems
}

export function walkSource(dir) {
  const files = {}
  const visit = (current) => {
    for (const entry of readdirSync(current)) {
      if (entry === 'node_modules' || entry === 'dist' || entry === 'generated' || entry.startsWith('.')) continue
      const full = join(current, entry)
      if (statSync(full).isDirectory()) {
        visit(full)
      } else if (/\.(tsx?|jsx?)$/.test(entry) && !entry.endsWith('.test.ts') && !entry.endsWith('.test.tsx')) {
        files[relative(root, full)] = readFileSync(full, 'utf8')
      }
    }
  }
  visit(dir)
  return files
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const problems = findNativeControls(walkSource(srcDir))
  if (problems.length > 0) {
    console.error(problems.map(({ file, line, tag }) => `FAIL: ${file}:${line} 使用原生 <${tag}>，请改用 design-system/Select 原语`).join('\n'))
    process.exit(1)
  }
  console.log('原生 select/datalist 静态检查通过')
}
