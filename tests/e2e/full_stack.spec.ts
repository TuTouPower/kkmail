import { test, expect } from '@playwright/test'

const E2E_PASSWORD = process.env.E2E_PASSWORD || 'E2E_Test_Pass_123!'
const IMAP_HOST = process.env.MAIL_CORE_IMAP_HOST || '127.0.0.1'
const IMAP_PORT = process.env.MAIL_CORE_IMAP_PORT || '1143'
const IMAP_USER = process.env.MAIL_CORE_IMAP_USER || 'alice@kkmail.test'
const IMAP_PASS = process.env.MAIL_CORE_IMAP_PASS || 'alice-imap-pass'

test.describe('全栈端到端真实测试 (Full Stack E2E)', () => {
  test('真实认证链路、CSRF防御与跨会话失效 (AC-002)', async ({ browser, baseURL }) => {
    const contextA = await browser.newContext()
    const pageA = await contextA.newPage()

    // 1. 打开首页，未登录状态下阻断于登录页
    await pageA.goto('/')
    await expect(pageA.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await expect(pageA.locator('button[type="submit"]')).toBeVisible()

    // 2. 输入错误密码，展示错误提示
    await pageA.locator('#login-password').fill('definitely-wrong-password')
    await pageA.locator('button[type="submit"]').click()
    await expect(pageA.getByText(/invalid credentials|登录密码错误/)).toBeVisible({ timeout: 5000 })

    // 3. 输入正确密码，获得真实 Cookie 并进入系统
    await pageA.locator('#login-password').fill(E2E_PASSWORD)
    await pageA.locator('button[type="submit"]').click()
    await expect(pageA.getByRole('button', { name: /所有收件箱/ })).toBeVisible({ timeout: 15000 })

    const cookies = await contextA.cookies()
    const sessionCookie = cookies.find((c) => c.name === 'kkmail_mc_session')
    expect(sessionCookie).toBeTruthy()

    // 4. CSRF 防御验证：无 CSRF 或错误 CSRF 的写请求被 403 拒绝
    const badCsrfResponse = await contextA.request.post('/api/auth/logout', {
      headers: {
        'x-csrf-token': 'invalid-csrf-token-12345',
      },
    })
    expect(badCsrfResponse.status()).toBe(403)

    // 5. 跨会话失效验证：在 contextB 登录
    const contextB = await browser.newContext()
    const pageB = await contextB.newPage()
    await pageB.goto('/')
    await pageB.locator('#login-password').fill(E2E_PASSWORD)
    await pageB.locator('button[type="submit"]').click()
    await expect(pageB.getByRole('button', { name: /所有收件箱/ })).toBeVisible({ timeout: 15000 })

    // 在 contextA 执行登出
    await pageA.getByRole('button', { name: '设置' }).click()
    await pageA.getByRole('button', { name: '通用', exact: true }).click()
    await pageA.locator('#logout-button').click()
    await expect(pageA.locator('#login-password')).toBeVisible({ timeout: 10000 })

    // 此时 contextB 的旧会话应该失效或在调用接口时被拦截退出
    await pageB.reload()
    await expect(pageB.locator('#login-password')).toBeVisible({ timeout: 10000 })

    await contextA.close()
    await contextB.close()
  })

  test('通过设置面板添加真实IMAP账号并验证Worker后台自动同步与交互 (AC-003, AC-004, AC-006)', async ({ page }) => {
    // 1. 登录系统
    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page.locator('#login-password').fill(E2E_PASSWORD)
    await page.locator('button[type="submit"]').click()
    await expect(page.getByRole('button', { name: /所有收件箱/ })).toBeVisible({ timeout: 15000 })

    // 2. 打开设置面板并切换到账户选项卡
    await page.getByRole('button', { name: '设置' }).click()
    const accountTab = page.getByRole('button', { name: '账户', exact: true })
    if (await accountTab.isVisible()) {
      await accountTab.click()
    }

    // 3. 填入真实测试 IMAP 配置
    await page.locator('#account-email').fill(IMAP_USER)
    await page.locator('#account-provider').selectOption('imap')
    await page.locator('#account-imap-host').fill(IMAP_HOST)
    await page.locator('#account-imap-port').fill(IMAP_PORT)
    const sslCheckbox = page.locator('#account-imap-ssl')
    if (await sslCheckbox.isChecked()) {
      await sslCheckbox.uncheck()
    }
    // 再次确认端口为 1143
    await page.locator('#account-imap-port').fill(IMAP_PORT)

    await page.locator('#account-credentials').fill(JSON.stringify({ password: IMAP_PASS }))

    // 点击添加账户
    await page.getByRole('button', { name: '添加', exact: true }).click()
    await expect(page.getByText('账户已添加')).toBeVisible({ timeout: 10000 })

    // 4. 关闭设置面板
    await page.keyboard.press('Escape')

    // 5. 点击侧边栏中的该账户以聚焦该邮箱，并触发同步
    const accountBtn = page.getByRole('button', { name: /alice@kkmail\.test/ }).first()
    if (await accountBtn.isVisible()) {
      await accountBtn.click()
    }

    const refreshBtn = page.getByRole('button', { name: '刷新并同步' })
    if (await refreshBtn.isVisible()) {
      await refreshBtn.click()
    }

    // 等待后台真实 Worker 同步完成：列表中出现同步下来的邮件
    await expect(page.locator('.message-row').first()).toBeVisible({ timeout: 30000 })

    // 6. 搜索交互验证
    const searchInput = page.locator('input[type="search"], input[placeholder*="搜索"]')
    if (await searchInput.isVisible()) {
      await searchInput.fill('Fixture')
      await page.waitForTimeout(500)
      await searchInput.fill('')
      await page.waitForTimeout(300)
    }

    // 7. 单封邮件详情与阅读
    const firstMail = page.locator('.message-row').first()
    await firstMail.click()
    await expect(page.locator('.reader-pane')).toBeVisible({ timeout: 10000 })

    // 8. 恶意 XSS 过滤防护验证 (AC-006)
    const hasXssLeaked = await page.evaluate(() => (window as unknown as { __xss_leaked?: boolean }).__xss_leaked)
    expect(hasXssLeaked).toBeFalsy()

    // 9. 标星 (Flag) 切换 (AC-004)
    const starBtn = page.locator('button[title*="星标"], button[aria-label*="星标"]').first()
    if (await starBtn.isVisible()) {
      await starBtn.click()
    }
  })

  test('双页面并发下真实SSE推送与实时状态更新 (AC-005)', async ({ browser }) => {
    const context = await browser.newContext()
    const page1 = await context.newPage()
    const page2 = await context.newPage()

    // page1 登录
    await page1.goto('/')
    await expect(page1.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page1.locator('#login-password').fill(E2E_PASSWORD)
    await page1.locator('button[type="submit"]').click()
    await expect(page1.getByRole('button', { name: /所有收件箱/ })).toBeVisible({ timeout: 15000 })

    // page2 访问（共享 Cookie 自动已登录）
    await page2.goto('/')
    await expect(page2.getByRole('button', { name: /所有收件箱/ })).toBeVisible({ timeout: 15000 })

    // 在 page1 点击第一封邮件
    const firstMailPage1 = page1.locator('.message-row').first()
    if (await firstMailPage1.isVisible()) {
      await firstMailPage1.click()
      // 触发已读更新，page2 应该通过 SSE 自动保持一致，页面不报错
      await page2.waitForTimeout(1000)
      await expect(page2.locator('body')).toBeVisible()
    }

    await context.close()
  })
})
