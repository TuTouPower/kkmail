import { test, expect } from '@playwright/test'

test.describe('kkmail E2E smoke tests', () => {
  test('login -> view mailbox list -> read message detail', async ({ page }) => {
    let authed = false

    // Mock auth check
    await page.route('**/api/auth/me', async (route) => {
      if (authed) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            via: 'session',
            csrf_token: 'test-csrf-token',
          }),
        })
      } else {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'unauthorized' }),
        })
      }
    })

    // Mock login endpoint
    await page.route('**/api/auth/login', async (route) => {
      authed = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: {
          'Set-Cookie': 'kkmail_mc_session=mock-token; Path=/; HttpOnly',
        },
        body: JSON.stringify({
          ok: true,
          csrf_token: 'test-csrf-token',
        }),
      })
    })

    // Mock accounts list
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: '00000000-0000-0000-0000-000000000001',
            email: 'user@example.com',
            provider: 'memory',
            status: 'active',
            display_name: 'Test Account',
          },
        ]),
      })
    })

    // Mock inbox list
    const mockMessageId = '00000000-0000-0000-0000-000000000002'
    await page.route('**/api/mail/inbox*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: mockMessageId,
              account_id: '00000000-0000-0000-0000-000000000001',
              sender: 'sender@example.com',
              sender_name: 'Sender Example',
              subject: '欢迎使用 kkmail 端到端测试',
              preview: '这是一封用于冒烟测试的测试邮件正文预览内容...',
              date: new Date().toISOString(),
              is_read: false,
              is_flagged: false,
              has_attachments: false,
            },
          ],
          has_more: false,
        }),
      })
    })

    // Mock message detail
    await page.route(`**/api/mail/messages/${mockMessageId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: mockMessageId,
          account_id: '00000000-0000-0000-0000-000000000001',
          sender: 'sender@example.com',
          sender_name: 'Sender Example',
          recipients: ['user@example.com'],
          subject: '欢迎使用 kkmail 端到端测试',
          body: '<p>这里是端到端测试的 HTML 格式邮件正文。</p>',
          body_type: 'html',
          date: new Date().toISOString(),
          is_read: true,
          is_flagged: false,
          has_attachments: false,
          attachments: [],
        }),
      })
    })

    // 1. Visit root page - unauthenticated shows LoginPage
    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible()

    // 2. Perform login
    await page.fill('#login-password', 'correct-password')
    await page.click('button[type="submit"]')

    // 3. Verify mailbox list is loaded
    const messageRow = page.locator('article.message-row')
    await expect(messageRow).toBeVisible()
    await expect(messageRow.locator('.subject')).toContainText('欢迎使用 kkmail 端到端测试')

    // 4. Click message row to view details in reader pane
    await messageRow.click()
    const readerPane = page.locator('.reader-pane')
    await expect(readerPane).toBeVisible()
    await expect(readerPane.locator('.detail-subject')).toContainText('欢迎使用 kkmail 端到端测试')
  })
})
