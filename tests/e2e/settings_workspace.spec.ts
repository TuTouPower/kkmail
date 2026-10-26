import { expect, test, type Page } from '@playwright/test'
import { FAKE_CSRF_TOKEN, setupStubApi } from './stubApi'

async function settingsFixture(page: Page) {
  const groups = [{ id: 'work', name: '工作邮箱', color: null, sort_order: 0 }]
  const accounts = Array.from({ length: 18 }, (_, index) => ({
    id: `settings-${index}`, email: index === 0 ? 'long-address-for-settings@gmail.com' : `account-${index}@example.com`,
    provider: 'imap', account_type: 'imap', group_id: index % 2 ? undefined : 'work',
    sync_enabled: index !== 1, sync_status: index === 0 ? 'auth_failed' : 'idle',
  }))
  await setupStubApi(page, { authedInitially: true, accounts, groups })
  await page.route('**/api/accounts**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/accounts' && request.method() === 'GET') return route.fulfill({ json: {
      accounts: accounts.map(account => ({ ...account, group_name: groups.find(group => group.id === account.group_id)?.name || null })),
      total: accounts.length, limit: 200, offset: 0, has_more: false,
    } })
    if (request.method() === 'PATCH') {
      expect(request.headers()['x-csrf-token']).toBe(FAKE_CSRF_TOKEN)
      const account = accounts.find(item => path === `/api/accounts/${item.id}`)!
      Object.assign(account, request.postDataJSON())
      return route.fulfill({ json: account })
    }
    return route.fallback()
  })
  await page.route('**/api/settings', route => route.fulfill({ json: { settings: { app_timezone: 'Asia/Shanghai', mail_fetch_timeout_seconds: '120' } } }))
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(page.getByRole('heading', { name: '账户管理' })).toBeVisible()
}

test('settings workspace: filters, sync preference, native modal keyboard and separate sections', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await settingsFixture(page)
  const settings = page.getByRole('region', { name: '应用设置' })
  await expect(settings.getByText('认证失败', { exact: true })).toBeVisible()
  await settings.getByRole('searchbox', { name: '搜索账户' }).fill('gmail.com')
  await expect(settings.locator('.settings-account-row')).toHaveCount(1)
  await settings.getByRole('switch', { name: '暂停同步 long-address-for-settings@gmail.com' }).click()
  await expect(settings.getByRole('switch', { name: '启用同步 long-address-for-settings@gmail.com' })).toHaveAttribute('aria-checked', 'false')
  await settings.getByRole('searchbox', { name: '搜索账户' }).fill('')
  await page.screenshot({ path: '../../.scratch/settings_design_review/current_accounts.png' })

  const add = settings.getByRole('button', { name: '添加账户', exact: true })
  await add.click()
  const dialog = page.getByRole('dialog', { name: '添加账户' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('邮箱地址')).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(add).toBeFocused()
  await expect(settings).toBeVisible()

  await settings.getByRole('button', { name: '分组管理', exact: true }).click()
  await settings.getByRole('button', { name: '查看 工作邮箱 的账户' }).click()
  await expect(settings.getByRole('combobox', { name: '按分组筛选' })).toHaveValue('work')
  await expect(settings.locator('.settings-account-row')).toHaveCount(9)
  await settings.getByRole('button', { name: '通用', exact: true }).click()
  await settings.getByRole('button', { name: '深色', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.screenshot({ path: '../../.scratch/settings_design_review/current_general.png' })
})

test('settings workspace: narrow layouts preserve account controls and avoid overflow', async ({ page }) => {
  await settingsFixture(page)
  const settings = page.getByRole('region', { name: '应用设置' })
  for (const width of [1100, 900, 761, 760, 390, 320]) {
    await page.setViewportSize({ width, height: 700 })
    await expect(settings.getByRole('button', { name: '添加账户', exact: true })).toBeVisible()
    await expect(settings.getByRole('combobox', { name: '移动 long-address-for-settings@gmail.com' })).toBeVisible()
    expect(await settings.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
    expect(await settings.locator('.settings-content').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
    if (width === 390) await page.screenshot({ path: '../../.scratch/settings_design_review/current_mobile_accounts.png' })
    await settings.getByRole('button', { name: '通用', exact: true }).click()
    await expect(settings.getByRole('button', { name: '跟随系统', exact: true })).toBeVisible()
    expect(await settings.locator('.settings-content').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
    if (width === 390) await page.screenshot({ path: '../../.scratch/settings_design_review/current_mobile_general.png' })
    await settings.getByRole('button', { name: '账户管理', exact: true }).click()
  }
  await settings.getByRole('button', { name: '添加账户', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '添加账户' })
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await settings.getByRole('checkbox', { name: '选择当前筛选的全部账户' }).check()
  await expect(settings.getByRole('button', { name: '移动分组', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 320, height: 568 })
  expect(await settings.locator('.settings-content').evaluate(node =>
    node.scrollHeight <= node.clientHeight || ['auto', 'scroll'].includes(getComputedStyle(node).overflowY),
  )).toBe(true)
  await settings.getByRole('button', { name: '同步全部账户', exact: true }).scrollIntoViewIfNeeded()
  await expect(settings.getByRole('button', { name: '同步全部账户', exact: true })).toBeVisible()
})
