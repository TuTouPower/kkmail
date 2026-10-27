import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
// Stylesheets are split by layer (A70): tokens.css holds only design
// tokens, base.css the element defaults, components.css the component
// rules. Tests read the concatenation in load order.
const tokensCss = readFileSync(resolve(__dirname, 'tokens.css'), 'utf8')
const baseCss = readFileSync(resolve(__dirname, 'base.css'), 'utf8')
const componentsCss = readFileSync(resolve(__dirname, 'components.css'), 'utf8')
const css = [tokensCss, baseCss, componentsCss].join('\n')

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

  it('keeps component rules out of the token stylesheet (A70)', () => {
    expect(tokensCss).not.toMatch(/\.app\s*\{/)
    expect(tokensCss).not.toMatch(/\.message-row\s*\{/)
    expect(baseCss).toMatch(/\*\s*\{\s*box-sizing: border-box;/)
    expect(componentsCss).toMatch(/\.app\s*\{/)
  })

  it('converges z-index on --z-* tokens (A70)', () => {
    expect(tokensCss).toMatch(/--z-titlebar:\s*100;/)
    expect(tokensCss).toMatch(/--z-popover:\s*1000;/)
    expect(baseCss).not.toMatch(/z-index:\s*\d+;/)
    expect(componentsCss).not.toMatch(/z-index:\s*\d+;/)
    expect(componentsCss).toContain('z-index: var(--z-')
  })

  it('loads the split stylesheets in tokens/base/components order (A70)', () => {
    const app = readFileSync(resolve(__dirname, '../App.tsx'), 'utf8')
    const tokensAt = app.indexOf("design-system/tokens.css'")
    const baseAt = app.indexOf("design-system/base.css'")
    const componentsAt = app.indexOf("design-system/components.css'")
    expect(tokensAt).toBeGreaterThanOrEqual(0)
    expect(baseAt).toBeGreaterThan(tokensAt)
    expect(componentsAt).toBeGreaterThan(baseAt)
  })

  // Replaces the deleted exact-color assertion: focused selection now derives colors from design tokens (A153).
  it('uses design tokens for focused selected items', () => {
    expect(css).toMatch(/\.message-list:focus-within \.message-row\.selected\s*\{[^}]*background:\s*var\(--primary\);/is)
    expect(css).toMatch(/\.message-list:focus-within \.message-row\.selected\s*\{[^}]*color:\s*var\(--on-primary\);/is)
    expect(css).toMatch(/\.message-list:focus-within \.message-row\.selected \.subject[^}]*color:\s*color-mix\(in srgb, var\(--on-primary\) 82%, var\(--primary\)\);/is)
    expect(css).toMatch(/\.message-row\.selected\s*\{[^}]*background:\s*var\(--selected\);/s)
  })
})
