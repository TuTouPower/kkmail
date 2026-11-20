import { expect, test } from '@playwright/test'
import { createMockMessages, setupStubApi } from './stubApi'
import { assertNoOverlap, setNarrowViewport } from './layoutGeometry'

const LONG_EMAIL = 'a-very-long-account-name-for-narrow-layout-regression@a-very-long-subdomain.example.com'

test('阅读页工具栏在 360px 窄屏不遮挡账号邮箱', async ({ page }) => {
  const message = { ...createMockMessages()[0], accountEmail: LONG_EMAIL }
  await setupStubApi(page, {
    authedInitially: true,
    messages: [message],
    accounts: [{
      id: 'acc-00000000-0000-0000-0000-000000000001',
      email: LONG_EMAIL,
      provider: 'imap',
      group_id: 'grp-1',
      sync_state: 'idle',
      sync_enabled: true,
      credential_state: 'valid',
      connectivity_state: 'connected',
      sync_activity: 'idle',
      last_connectivity_error: null,
    }],
  })

  await setNarrowViewport(page)
  await page.goto('/')
  await expect(page.getByText(message.subject)).toBeVisible({ timeout: 10000 })
  await page.getByText(message.subject).first().click()
  await expect(page.locator('.detail-subject')).toContainText(message.subject, { timeout: 5000 })

  await assertNoOverlap(page, '.reader-location', '.reader-toolbar-actions')
  await expect(page.locator('.reader-location')).toContainText(LONG_EMAIL)
})
