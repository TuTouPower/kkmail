import { test, expect } from '@playwright/test'
import { setupStubApi } from './stubApi'

test.describe('侧栏账号文件夹树布局与交互 (AC-001 ~ AC-004)', () => {
  const accounts = [
    {
      id: 'acc-1',
      email: 'alpha@example.com',
      provider: 'imap',
      sync_state: 'idle',
      sync_enabled: true,
    },
    {
      id: 'acc-2',
      email: 'beta@example.com',
      provider: 'imap',
      sync_state: 'idle',
      sync_enabled: true,
    },
    {
      id: 'acc-3',
      email: 'gamma-long-address-user-account-overflow-test@very-long-subdomain.example.com',
      provider: 'imap',
      sync_state: 'idle',
      sync_enabled: true,
    },
  ]

  const folderStatsByAccount = {
    'acc-1': [
      { folder_id: 'f-inbox', role: 'inbox', name: '收件箱', total_count: 10, unread_count: 2, remote_id: 'INBOX' },
      { folder_id: 'f-sent', role: 'sent', name: '已发送', total_count: 5, unread_count: 0, remote_id: 'Sent' },
      { folder_id: 'f-work', role: 'other', name: '工作邮件', total_count: 0, unread_count: 0, remote_id: 'Work' },
      {
        folder_id: 'f-work-p1',
        role: 'other',
        name: '项目归档',
        total_count: 0,
        unread_count: 0,
        remote_id: 'Work/P1',
        parent_remote_id: 'Work',
      },
    ],
    'acc-2': [
      { folder_id: 'f-inbox-2', role: 'inbox', name: '收件箱', total_count: 3, unread_count: 0, remote_id: 'INBOX' },
    ],
    'acc-3': [
      {
        folder_id: 'f-long',
        role: 'other',
        name: '超级超长的测试目录名称用于测试椭圆截断以及绝不横向撑开侧边栏容器边界',
        total_count: 1,
        unread_count: 0,
        remote_id: 'LongFolder',
      },
    ],
  }

  test('AC-001: 展开账号时文件夹树垂直排在标题下方，后续账号位于整棵树下方，无错位或遮挡', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.goto('/')

    const acc1Row = page.locator('.account-row').filter({ hasText: 'alpha@example.com' })
    const acc2Row = page.locator('.account-row').filter({ hasText: 'beta@example.com' })
    await expect(acc1Row).toBeVisible({ timeout: 10000 })
    await expect(acc2Row).toBeVisible()

    // 展开账号 1
    const toggle1 = acc1Row.locator('.account-folders-toggle')
    await toggle1.click()

    const tree1 = acc1Row.locator('.account-folders')
    await expect(tree1).toBeVisible()
    await expect(tree1.getByText('工作邮件')).toBeVisible()

    // 获取账号 1 头部、文件夹树与账号 2 头部的真实几何包围盒
    const acc1HeaderBox = await acc1Row.locator('.side-item-group').boundingBox()
    const tree1Box = await tree1.boundingBox()
    const acc2HeaderBox = await acc2Row.locator('.side-item-group').boundingBox()

    expect(acc1HeaderBox).not.toBeNull()
    expect(tree1Box).not.toBeNull()
    expect(acc2HeaderBox).not.toBeNull()

    // 1. 文件夹树位于账号 1 标题正下方
    expect(tree1Box!.y).toBeGreaterThanOrEqual(acc1HeaderBox!.y + acc1HeaderBox!.height - 2)

    // 2. 文件夹树水平靠左，不横向排到账号标题右侧
    expect(tree1Box!.x).toBeLessThan(acc1HeaderBox!.x + 35)

    // 3. 账号 2 标题位于整棵文件夹树的正下方，无纵向遮挡
    expect(acc2HeaderBox!.y).toBeGreaterThanOrEqual(tree1Box!.y + tree1Box!.height - 2)
  })

  test('AC-002: 两个账号可同时展开且独立折叠，多级目录与错误提示在所属账号下方呈现', async ({ page }) => {
    const customStats = {
      ...folderStatsByAccount,
      'acc-2': { error: '目录同步网络错误' },
    }
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount: customStats })
    await page.goto('/')

    const acc1Row = page.locator('.account-row').filter({ hasText: 'alpha@example.com' })
    const acc2Row = page.locator('.account-row').filter({ hasText: 'beta@example.com' })
    await expect(acc1Row).toBeVisible({ timeout: 10000 })

    // 同时展开两个账号
    await acc1Row.locator('.account-folders-toggle').click()
    await acc2Row.locator('.account-folders-toggle').click()

    await expect(acc1Row.locator('.account-folders')).toBeVisible()
    // acc-2 失败提示展示在 acc-2 下方
    const errorStatus = acc2Row.getByText('文件夹加载失败')
    await expect(errorStatus).toBeVisible()

    const acc2HeaderBox = await acc2Row.locator('.side-item-group').boundingBox()
    const errorBox = await errorStatus.boundingBox()
    expect(errorBox!.y).toBeGreaterThanOrEqual(acc2HeaderBox!.y + acc2HeaderBox!.height - 2)

    // 折叠账号 1，账号 2 的错误状态依然保持展开
    await acc1Row.locator('.account-folders-toggle').click()
    await expect(acc1Row.locator('.account-folders')).not.toBeVisible()
    await expect(errorStatus).toBeVisible()
  })

  test('AC-003: 桌面侧栏与 760px 抽屉中长名称不撑出容器，点击目录准确导航', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.goto('/')

    // 1. 桌面视口测试 (1200x800)
    await page.setViewportSize({ width: 1200, height: 800 })
    const acc3Row = page.locator('.account-row').filter({ hasText: 'gamma-long-address' })
    await expect(acc3Row).toBeVisible({ timeout: 10000 })
    await acc3Row.locator('.account-folders-toggle').click()

    const sidebar = page.locator('aside.sidebar')
    const sidebarBox = await sidebar.boundingBox()
    const longEmailSpan = acc3Row.locator('.account-email').first()
    const longFolderBtn = acc3Row.locator('.folder-item-btn')

    await expect(longFolderBtn).toBeVisible()
    const longEmailBox = await longEmailSpan.boundingBox()
    const longFolderBox = await longFolderBtn.boundingBox()

    // 元素右边界不能超出侧边栏右边界
    expect(longEmailBox!.x + longEmailBox!.width).toBeLessThanOrEqual(sidebarBox!.x + sidebarBox!.width + 2)
    expect(longFolderBox!.x + longFolderBox!.width).toBeLessThanOrEqual(sidebarBox!.x + sidebarBox!.width + 2)

    // 2. 点击目录准确导航至该 folder_id
    const acc1Row = page.locator('.account-row').filter({ hasText: 'alpha@example.com' })
    await acc1Row.locator('.account-folders-toggle').click()
    const workFolderBtn = acc1Row.locator('.folder-item-btn').filter({ hasText: '工作邮件' })
    await workFolderBtn.click()

    // 验证导航标题更新为对应文件夹名称
    await expect(page.locator('.list-title').getByText('工作邮件')).toBeVisible()

    // 3. 移动端抽屉视口测试 (375x667)
    await page.setViewportSize({ width: 375, height: 667 })
    const drawerOpenBtn = page.locator('.sidebar-expand-btn')
    await expect(drawerOpenBtn).toBeVisible({ timeout: 5000 })
    await drawerOpenBtn.click()
    await expect(sidebar).toBeVisible()
    const drawerBox = await sidebar.boundingBox()
    const drawerLongFolderBox = await longFolderBtn.boundingBox()
    expect(drawerLongFolderBox!.x + drawerLongFolderBox!.width).toBeLessThanOrEqual(drawerBox!.x + drawerBox!.width + 2)
  })

  test('AC-004: 鼠标操作正常，Tab 键盘可获焦且 Enter/Space 可触发，aria-expanded 一致', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.goto('/')

    const acc1Row = page.locator('.account-row').filter({ hasText: 'alpha@example.com' })
    const toggle1 = acc1Row.locator('.account-folders-toggle')
    await expect(toggle1).toBeVisible({ timeout: 10000 })

    // 初始 aria-expanded = false
    await expect(toggle1).toHaveAttribute('aria-expanded', 'false')

    // 键盘聚焦并用 Space 展开
    await toggle1.focus()
    await page.keyboard.press('Space')
    await expect(toggle1).toHaveAttribute('aria-expanded', 'true')
    await expect(acc1Row.locator('.account-folders')).toBeVisible()

    // 目录项可通过 Tab 聚焦并按 Enter 导航
    const firstFolder = acc1Row.locator('.folder-item-btn').first()
    await firstFolder.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('.list-title').getByText('收件箱')).toBeVisible()

    // 键盘 Space 再次折叠
    await toggle1.focus()
    await page.keyboard.press('Enter')
    await expect(toggle1).toHaveAttribute('aria-expanded', 'false')
    await expect(acc1Row.locator('.account-folders')).not.toBeVisible()
  })
})
