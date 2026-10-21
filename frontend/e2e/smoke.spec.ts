import { test, expect } from '@playwright/test'
import { setupStubApi } from './stubApi'

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
    await expect(page.getByRole('button', { name: /所有收件箱/ })).toBeVisible({ timeout: 10000 })
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

    // 2. 点击第一封邮件，右侧读信区域正确展示
    await page.getByText('欢迎体验 kkmail 邮件内核').first().click()
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
})
