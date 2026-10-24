import { expect, test } from '@playwright/test'
import { setupStubApi } from './stubApi'

test('provider forms: Google IMAP help, Microsoft OAuth and nested dialog focus on narrow screens', async ({ page }) => {
  await setupStubApi(page, { authedInitially: true })
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('button', { name: '添加账户', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '添加账户', exact: true })
  await dialog.getByLabel('邮箱供应商').selectOption('google')
  await dialog.getByLabel('连接方式').selectOption('imap')
  await expect(dialog.getByLabel('IMAP 服务器')).toHaveValue('imap.gmail.com')
  const helpButton = dialog.getByRole('button', { name: '如何获取账户凭据' })
  await helpButton.click()
  await expect(page.getByRole('dialog', { name: /IMAP 凭据获取/ })).toContainText('两步验证')
  await page.keyboard.press('Escape')
  await expect(helpButton).toBeFocused()
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('邮箱供应商').selectOption('microsoft')
  await expect(dialog.getByLabel('Client ID', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('IMAP 服务器')).toHaveCount(0)
  await dialog.getByLabel('Refresh Token', { exact: true }).fill('long-token'.repeat(100))
  await page.setViewportSize({ width: 320, height: 568 })
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).not.toBeVisible()
})

test('provider forms: Google OAuth redirect sign-in, verified email recovery and reauthorization', async ({ page }) => {
  await setupStubApi(page, {
    authedInitially: true,
    accounts: [
      {
        id: 'acc-gmail-existing',
        email: 'existing-oauth@gmail.com',
        provider: 'gmail',
        account_type: 'gmail',
        group_id: 'grp-1',
        sync_state: 'auth_failed',
        sync_enabled: true,
      },
    ],
  })
  await page.addInitScript(() => {
    window.open = () => ({ closed: false } as unknown as Window)
  })
  await page.goto('/')
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await page.getByRole('button', { name: '添加账户', exact: true }).click()

  const addDialog = page.getByRole('dialog', { name: '添加账户', exact: true })
  await addDialog.getByLabel('邮箱供应商').selectOption('google')
  await expect(addDialog.getByLabel('OAuth 回调地址（Redirect URI）')).toHaveValue(
    'http://127.0.0.1:18765/api/accounts/oauth/callback/google',
  )
  await addDialog.getByLabel('Client ID', { exact: true }).fill('desktop-google-client-id')
  await addDialog.getByRole('button', { name: '使用 Google 登录', exact: true }).click()
  await expect(addDialog).toContainText('已完成 Google 授权：oauth-new@gmail.com')
  await expect(addDialog.getByLabel('邮箱地址')).toHaveValue('oauth-new@gmail.com')
  await page.goto('/#oauth-return')
  await expect(addDialog).toBeVisible()
  await expect(addDialog.getByLabel('邮箱地址')).toHaveValue('oauth-new@gmail.com')
  await expect(addDialog.getByLabel('Client ID', { exact: true })).toHaveValue('desktop-google-client-id')
  await addDialog.getByRole('button', { name: '添加', exact: true }).click()
  await expect(addDialog).not.toBeVisible()
  await expect(page.getByRole('region', { name: '账户列表' }).getByText('oauth-new@gmail.com')).toBeVisible()

  // Reauthorize and save the existing account through the production PATCH client.
  await page.getByRole('button', { name: '编辑账户 existing-oauth@gmail.com', exact: true }).click()
  const editDialog = page.getByRole('dialog', { name: '编辑账户', exact: true })
  await editDialog.getByRole('button', { name: '重新授权', exact: true }).click()
  await expect(editDialog).toContainText('已完成 Google 授权：existing-oauth@gmail.com')
  const patchRequest = page.waitForRequest(req => req.method() === 'PATCH' && req.url().endsWith('/api/accounts/acc-gmail-existing'))
  await editDialog.getByRole('button', { name: '保存修改', exact: true }).click()
  expect((await patchRequest).postDataJSON()).toMatchObject({ oauth_flow_id: 'stub-oauth-flow-1' })
  await expect(editDialog).not.toBeVisible()
})
