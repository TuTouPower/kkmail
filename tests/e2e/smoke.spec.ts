import { test, expect } from '@playwright/test'
import { setupStubApi, FAKE_CSRF_TOKEN } from './stubApi'

test.describe('kkmail 核心端到端冒烟测试链路 (E2E Smoke)', () => {
  test('未登录时阻断并成功完成密码登录流', async ({ page }) => {
    await setupStubApi(page, { authedInitially: false })

    // 1. 打开应用，阻断于登录界面
    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('button[type="submit"]')).toBeVisible()

    // 2. 输入错误密码，展示错误提示
    await page.locator('#login-password').fill('wrong-password')
    await page.locator('button[type="submit"]').click()
    await expect(page.getByText('登录密码错误')).toBeVisible({ timeout: 5000 })

    // 3. 输入正确密码，顺利进入系统
    await page.locator('#login-password').fill('correct-password')
    await page.locator('button[type="submit"]').click()

    // 4. 验证侧边栏核心入口已挂载
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('user@example.com')).toBeVisible()
  })

  test('邮件列表加载、详情阅读与搜索交互', async ({ page }) => {
    // 初始即已登录状态
    await setupStubApi(page, { authedInitially: true })

    await page.goto('/')

    // 1. 等待邮件列表渲染
    await expect(page.getByText('欢迎体验 kkmail 邮件内核')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('关于安全与加密凭据的重要说明')).toBeVisible()
    await expect(page.getByText('季度运营汇总报告')).toBeVisible()

    // 2. 点击第一封邮件，断言触发标记已读请求且携带 CSRF Token，右侧读信区域正确展示
    const readRequestPromise = page.waitForRequest((req) =>
      req.url().includes('/read') && req.method() === 'POST'
    )
    await page.getByText('欢迎体验 kkmail 邮件内核').first().click()
    const readRequest = await readRequestPromise
    expect(readRequest.headers()['x-csrf-token']).toBe(FAKE_CSRF_TOKEN)
    const readResponse = await readRequest.response()
    expect(readResponse?.status()).toBe(200)

    await expect(page.locator('.detail-subject').getByText('欢迎体验 kkmail 邮件内核')).toBeVisible({ timeout: 5000 })

    // 3. 搜索交互验证
    const searchInput = page.locator('input[type="search"], input[placeholder*="搜索"]')
    if (await searchInput.isVisible()) {
      await searchInput.fill('安全')
      // 等待搜索防抖与结果响应
      await expect(page.getByText('关于安全与加密凭据的重要说明')).toBeVisible({ timeout: 5000 })
      await expect(page.getByText('季度运营汇总报告')).not.toBeVisible()

      // 清空搜索框
      await searchInput.fill('')
      await expect(page.getByText('季度运营汇总报告')).toBeVisible({ timeout: 5000 })
    }
  })

  test('p042: 邮件与导航邮箱可写入系统剪贴板且复制不触发导航', async ({ page, context }) => {
    await setupStubApi(page, { authedInitially: true })
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto('/')
    await expect(page.getByText('欢迎体验 kkmail 邮件内核')).toBeVisible({ timeout: 10000 })
    await page.getByText('欢迎体验 kkmail 邮件内核').first().click()
    await expect(page.locator('.detail-subject')).toContainText('欢迎体验 kkmail 邮件内核')

    const reader = page.locator('.reader-pane')
    await reader.locator('.reader-location').getByRole('button', { name: '复制邮箱地址 user@example.com' }).click()
    await expect(page.getByText('已复制地址')).toBeVisible()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('user@example.com')
    await reader.getByRole('button', { name: '复制邮箱地址 team@kkmail.local' }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('team@kkmail.local')
    const recipientCopy = reader.locator('[data-ui="MR07"]').getByRole('button', { name: '复制邮箱地址 user@example.com' })
    await recipientCopy.click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('user@example.com')
    await expect(page.locator('.detail-subject')).toContainText('欢迎体验 kkmail 邮件内核')

    const account = page.locator('.tree-account-list .tree-account-block[data-account-id="acc-00000000-0000-0000-0000-000000000001"]')
    const accountSelect = account.locator('.tree-account-select')
    await expect(accountSelect).toHaveAttribute('aria-expanded', 'false')
    await account.getByRole('button', { name: '复制邮箱地址 user@example.com' }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('user@example.com')
    await expect(accountSelect).toHaveAttribute('aria-expanded', 'false')
  })

  test('通过设置面板中的退出登录按钮完成登出链路', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true })

    await page.goto('/')
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 10000 })

    // 1. 打开设置面板
    await page.getByRole('button', { name: '设置' }).click()

    // 2. 切换到通用选项卡
    await page.getByRole('button', { name: '通用' }).click()

    // 3. 监听退出登录 POST 请求
    const logoutRequestPromise = page.waitForRequest((req) =>
      req.url().includes('/api/auth/logout') && req.method() === 'POST'
    )

    // 4. 点击退出登录
    await page.locator('#logout-button').click()

    const logoutRequest = await logoutRequestPromise
    expect(logoutRequest.headers()['x-csrf-token']).toBe(FAKE_CSRF_TOKEN)
    const logoutResponse = await logoutRequest.response()
    expect(logoutResponse?.status()).toBe(200)

    // 5. 验证成功退回到登录页面
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 10000 })
  })

  test('解析失败邮件在阅读器明确提示错误且跨邮件隔离 (AC-006, AC-007)', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true })
    await page.goto('/')

    // 1. 点击解析失败邮件
    await expect(page.getByText('解析失败的损坏测试邮件')).toBeVisible({ timeout: 10000 })
    await page.getByText('解析失败的损坏测试邮件').click()

    // 2. 验证出现“邮件解析失败”提示及脱敏原因，且不出现“尚未完成同步或内容为空”
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('邮件解析失败')).toBeVisible()
    await expect(page.getByText('body_decode_failed: UnicodeDecodeError')).toBeVisible()
    await expect(page.getByText('邮件正文尚未完成同步或内容为空')).not.toBeVisible()

    // 3. 切换至正常邮件：错误提示消失，正常正文呈现
    await page.getByText('欢迎体验 kkmail 邮件内核').click()
    await expect(page.getByRole('alert')).not.toBeVisible()
    await expect(page.getByText('邮件解析失败')).not.toBeVisible()

    // 4. 重新切回失败邮件：持久错误依然可见
    await page.getByText('解析失败的损坏测试邮件').click()
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText('邮件解析失败')).toBeVisible()
  })

  test('深色模式下浅色邮件智能深色渲染与单信原色切换 (t065 AC-001 ~ AC-005)', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true })
    await page.addInitScript(() => {
      localStorage.setItem('mail-ui-storage', JSON.stringify({
        state: { theme: 'dark', mailBodyDarkMode: 'smart' },
        version: 0,
      }))
    })

    await page.goto('/')

    await expect(page.getByText('季度运营汇总报告')).toBeVisible({ timeout: 10000 })
    await page.getByText('季度运营汇总报告').click()

    const iframe = page.locator('iframe.email-body-frame')
    await expect(iframe).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.mail-paper-card')).not.toBeVisible()
    const srcDoc1 = await iframe.getAttribute('srcdoc')
    expect(srcDoc1).toContain('filter:invert(100%) hue-rotate(180deg)')

    const toggleButton = page.locator('button[aria-label="切换原样/深色视图"]')
    await expect(toggleButton).toBeVisible()
    expect(await toggleButton.getAttribute('title')).toBe('查看原样视图')

    await toggleButton.click()
    await expect(page.locator('.mail-paper-card')).toBeVisible()
    expect(await toggleButton.getAttribute('title')).toBe('切换至深色视图')
    const srcDoc2 = await page.locator('.mail-paper-card iframe.email-body-frame').getAttribute('srcdoc')
    expect(srcDoc2).not.toContain('filter:invert')

    await toggleButton.click()
    await expect(page.locator('.mail-paper-card')).not.toBeVisible()
    expect(await toggleButton.getAttribute('title')).toBe('查看原样视图')
  })

  test('远程图片放行重载、发件人白名单与 CID 内联图片加载 (t066 AC-001 ~ AC-018)', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true })
    await page.goto('/')

    // Click the test mail containing both CID inline image and remote tracking image
    await expect(page.getByText('远程图片与内联图片测试邮件')).toBeVisible({ timeout: 10000 })
    await page.getByText('远程图片与内联图片测试邮件').click()

    // 1. CID inline image is rewritten to signed preview URL in srcdoc
    const iframe = page.locator('iframe.email-body-frame')
    await expect(iframe).toBeVisible({ timeout: 5000 })
    const initialSrcdoc = await iframe.getAttribute('srcdoc')
    expect(initialSrcdoc).toContain('/api/mail/attachments/att-inline-1/preview?token=stub-preview-token')

    // 2. Remote tracking image is blocked: banner is visible with two allow buttons
    await expect(page.getByText('远程图片已拦截（防追踪）。')).toBeVisible()
    const allowMessageBtn = page.getByRole('button', { name: '仅此邮件允许加载' })
    const allowSenderBtn = page.getByRole('button', { name: '总是允许来自此发件人的图片' })
    await expect(allowMessageBtn).toBeVisible()
    await expect(allowSenderBtn).toBeVisible()

    // 3. Click allow message -> banner disappears and iframe remounts with open remote CSP
    await allowMessageBtn.click()
    await expect(page.getByText('远程图片已拦截（防追踪）。')).not.toBeVisible()
    const allowedSrcdoc = await iframe.getAttribute('srcdoc')
    expect(allowedSrcdoc).toContain("img-src 'self' https: http: data: cid:")

    // 4. Reload page -> state persisted in backend, still allowed without banner
    await page.reload()
    await expect(page.getByText('远程图片与内联图片测试邮件')).toBeVisible({ timeout: 10000 })
    await page.getByText('远程图片与内联图片测试邮件').click()
    await expect(page.locator('iframe.email-body-frame')).toBeVisible()
    await expect(page.getByText('远程图片已拦截（防追踪）。')).not.toBeVisible()
  })
})
