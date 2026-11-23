import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { setupStubApi } from './stubApi'

const groups = [{ id: 'work', name: '工作邮箱', color: null, sort_order: 0 }]
const accounts = [{ id: 'ms-existing', email: 'ms@example.test', provider: 'graph', account_type: 'graph', sync_enabled: true, group_id: 'work' }]

async function assertThemedPopover(page: Page, trigger: Locator, name: string) {
  await expect(trigger).toBeVisible()
  await trigger.click()
  const popover = page.locator('[data-select-open="true"]').last()
  await expect(popover).toBeVisible()
  const styles = await page.evaluate(() => {
    const element = [...document.querySelectorAll('[data-select-open="true"]')].at(-1) as HTMLElement
    const computed = getComputedStyle(element)
    const probe = document.createElement('div')
    document.body.appendChild(probe)
    const read = (property: 'backgroundColor' | 'borderColor' | 'borderRadius', token: string) => {
      probe.style.cssText = ''
      probe.style[property] = `var(${token})`
      return getComputedStyle(probe)[property]
    }
    const result = {
      background: computed.backgroundColor,
      border: computed.borderColor,
      radius: computed.borderRadius,
      tokenBackground: read('backgroundColor', '--dropdown-surface'),
      tokenBorder: read('borderColor', '--dropdown-border'),
      tokenRadius: read('borderRadius', '--dropdown-radius'),
      selectedBackground: '',
      tokenActive: read('backgroundColor', '--dropdown-active'),
      activeBackground: '',
      tokenHover: read('backgroundColor', '--dropdown-hover'),
    }
    probe.remove()
    const selected = element.querySelector('[aria-selected="true"]') as HTMLElement | null
    if (selected) result.selectedBackground = getComputedStyle(selected).backgroundColor
    const active = element.querySelector('.ds-select-option.is-active') as HTMLElement | null
    if (active) result.activeBackground = getComputedStyle(active).backgroundColor
    return result
  })
  expect(styles.background, `${name} background`).toBe(styles.tokenBackground)
  expect(styles.border, `${name} border`).toBe(styles.tokenBorder)
  expect(styles.radius, `${name} radius`).toBe(styles.tokenRadius)
  if (styles.selectedBackground) expect(styles.selectedBackground, `${name} selected highlight`).toBe(styles.tokenActive)
  else expect(styles.activeBackground, `${name} active highlight`).toBe(styles.tokenHover)
  const theme = await page.locator('html').getAttribute('data-theme')
  const dir = join(process.cwd(), '.scratch')
  mkdirSync(dir, { recursive: true })
  await page.screenshot({ path: join(dir, `t085_${name}_${theme}.png`) })
  await trigger.click()
}

for (const theme of ['dark', 'light'] as const) {
  test(`dropdown popovers use design tokens in ${theme} theme`, async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, groups })
    await page.route('**/api/settings', route => route.fulfill({ json: { settings: { app_timezone: 'Asia/Shanghai', mail_fetch_timeout_seconds: '120' } } }))
    await page.goto('/')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    const settings = page.getByRole('region', { name: '应用设置' })
    await expect(settings).toBeVisible()
    await settings.getByRole('button', { name: '通用', exact: true }).click()
    await settings.getByRole('button', { name: theme === 'dark' ? '深色' : '亮色', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)

    await settings.getByRole('button', { name: '账户管理', exact: true }).click()
    await assertThemedPopover(page, settings.getByRole('combobox', { name: '按分组筛选' }), 'group_filter')

    await settings.getByRole('button', { name: '账户管理', exact: true }).click()
    await settings.getByRole('button', { name: '添加账户', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '添加账户', exact: true })
    await assertThemedPopover(page, dialog.locator('#account-vendor'), 'vendor')
    await assertThemedPopover(page, dialog.locator('#account-group'), 'account_group')

    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await settings.getByRole('button', { name: '编辑账户 ms@example.test', exact: true }).click()
    const edit = page.getByRole('dialog', { name: '编辑账户', exact: true })
    await assertThemedPopover(page, edit.locator('#account-tenant'), 'tenant_suggestions')
    await edit.getByRole('button', { name: '取消', exact: true }).click()

    await settings.getByRole('button', { name: '通用', exact: true }).click()
    await assertThemedPopover(page, settings.locator('#settings-timezone'), 'timezone_suggestions')
  })
}
