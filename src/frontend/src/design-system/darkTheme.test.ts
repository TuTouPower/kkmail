import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(resolve(__dirname, 'tokens.css'), 'utf8')

describe('Dark mode Apple Mail theme and contrast (AC-001, AC-002)', () => {
  it('declares exact Apple Mail dark mode color tokens (AC-001)', () => {
    // 侧栏 #1C1F21、列表 #212628、阅读容器 #222729
    expect(css).toMatch(/--sidebar:\s*#1C1F21;/i)
    expect(css).toMatch(/--list:\s*#212628;/i)
    expect(css).toMatch(/--reader:\s*#222729;/i)
    // 边框 #2C3235
    expect(css).toMatch(/--line:\s*#2C3235;/i)
    // 列表悬停 #2B3134
    expect(css).toMatch(/--surface-hover:\s*#2B3134;/i)
    // 未读点 #0A84FF
    expect(css).toMatch(/--accent:\s*#0A84FF;/i)
    // 主文本 #FFFFFF、辅助文本 #8E8E93、次级文本 #E4E4E6、图标 #98989D、图标悬停 #FFFFFF
    expect(css).toMatch(/--text:\s*#FFFFFF;/i)
    expect(css).toMatch(/--subtle:\s*#E4E4E6;/i)
    expect(css).toMatch(/--muted:\s*#8E8E93;/i)
    expect(css).toMatch(/--icon:\s*#98989D;/i)
    expect(css).toMatch(/--icon-hover:\s*#FFFFFF;/i)
  })

  it('defines sender font-weight as 600 (AC-001)', () => {
    // .sender font-weight 600
    expect(css).toMatch(/\.sender\s*\{[^}]*font-weight:\s*600;/s)
  })

  it('keeps reader toolbar keyboard focus visible with the shared accent token', () => {
    expect(css).toMatch(/button:focus-visible[\s\S]*?\{[^}]*outline:\s*2px solid var\(--accent\);/)
    expect(css).not.toMatch(/\.reader-action:focus(?:-visible)?\s*[,{}]/)
  })

  it('configures focused selected and unfocused selected item styling (AC-002)', () => {
    // 聚焦选中：.message-list:focus-within .message-row.selected
    expect(css).toContain('.message-list:focus-within .message-row.selected')
    expect(css).toMatch(/\.message-list:focus-within \.message-row\.selected\s*\{[^}]*background:\s*#0A60FE;/is)
    expect(css).toMatch(/\.message-list:focus-within \.message-row\.selected\s*\{[^}]*color:\s*#FFFFFF;/is)

    // 时间与副标题变为 #D0E2FF
    expect(css).toMatch(/\.message-list:focus-within \.message-row\.selected \.subject[^}]*color:\s*#D0E2FF;/is)

    // 失焦选中：.message-row.selected 背景使用 --selected (#323236 in dark mode)
    expect(css).toMatch(/\.message-row\.selected\s*\{[^}]*background:\s*var\(--selected\);/s)
  })
})
