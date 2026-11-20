#!/usr/bin/env node
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const breakpointsSrc = readFileSync(resolve(root, 'src/design-system/breakpoints.ts'), 'utf8')
const css = readFileSync(resolve(root, 'src/design-system/components.css'), 'utf8')

const problems = []

const objectBody = breakpointsSrc.match(/BREAKPOINTS\s*=\s*\{([\s\S]*?)\}/)?.[1]
if (!objectBody) {
  problems.push('breakpoints.ts: 找不到 BREAKPOINTS 定义')
} else {
  const configured = new Set(
    [...objectBody.matchAll(/[A-Za-z]+\s*:\s*(\d+)/g)].map((match) => Number(match[1])),
  )
  const mobileMatch = objectBody.match(/mobile\s*:\s*(\d+)/)
  if (!mobileMatch) {
    problems.push('breakpoints.ts: 缺少 mobile 断点')
  } else {
    const mobile = Number(mobileMatch[1])
    const mediaValues = [...css.matchAll(/@media([^{]+)\{/g)]
      .flatMap((match) => [...match[1].matchAll(/max-width:\s*(\d+)px/g)].map((width) => Number(width[1])))
    if (!mediaValues.includes(mobile)) {
      problems.push(`components.css: 没有使用 mobile 断点 ${mobile}px 的媒体查询`)
    }
    for (const value of mediaValues) {
      if (!configured.has(value)) {
        problems.push(`components.css: @media max-width ${value}px 不在 breakpoints.ts 的单一来源中`)
      }
    }
  }
}

const actionsStart = css.indexOf('.app-toolbar-actions,')
if (actionsStart < 0) {
  problems.push('components.css: 缺少共享 .app-toolbar-actions 契约')
} else {
  const block = css.slice(actionsStart, css.indexOf('}', actionsStart))
  if (/position\s*:\s*absolute/.test(block) || /translate\s*\(/.test(block)) {
    problems.push('components.css: 工具栏操作区仍使用绝对定位覆盖主信息')
  }
  if (!/\bflex\s*:\s*0\s+0\s+auto/.test(block)) {
    problems.push('components.css: 工具栏操作区缺少 flex:0 0 auto 收缩保护')
  }
}

if (problems.length > 0) {
  console.error(problems.map((problem) => `FAIL: ${problem}`).join('\n'))
  process.exit(1)
}
console.log('布局契约与断点单一来源检查通过')
