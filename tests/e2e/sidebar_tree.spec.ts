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

    const acc1Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'alpha@example.com' })
    const acc2Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'beta@example.com' })
    await expect(acc1Row).toBeVisible({ timeout: 10000 })
    await expect(acc2Row).toBeVisible()

    // 展开账号 1
    const toggle1 = acc1Row.locator('.tree-disclosure')
    await toggle1.click()

    const tree1 = acc1Row.locator('.tree-folder-list')
    await expect(tree1).toBeVisible()
    await expect(tree1.getByText('工作邮件')).toBeVisible()

    // 获取账号 1 头部、文件夹树与账号 2 头部的真实几何包围盒
    const acc1HeaderBox = await acc1Row.locator('.tree-account-row').boundingBox()
    const tree1Box = await tree1.boundingBox()
    const acc2HeaderBox = await acc2Row.locator('.tree-account-row').boundingBox()

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

    const acc1Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'alpha@example.com' })
    const acc2Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'beta@example.com' })
    await expect(acc1Row).toBeVisible({ timeout: 10000 })

    // 同时展开两个账号
    await acc1Row.locator('.tree-disclosure').click()
    await acc2Row.locator('.tree-disclosure').click()

    await expect(acc1Row.locator('.tree-folder-list')).toBeVisible()
    // acc-2 失败提示展示在 acc-2 下方
    const errorStatus = acc2Row.getByText('文件夹加载失败')
    await expect(errorStatus).toBeVisible()

    const acc2HeaderBox = await acc2Row.locator('.tree-account-row').boundingBox()
    const errorBox = await errorStatus.boundingBox()
    expect(errorBox!.y).toBeGreaterThanOrEqual(acc2HeaderBox!.y + acc2HeaderBox!.height - 2)

    // 折叠账号 1，账号 2 的错误状态依然保持展开
    await acc1Row.locator('.tree-disclosure').click()
    await expect(acc1Row.locator('.tree-folder-list')).not.toBeVisible()
    await expect(errorStatus).toBeVisible()
  })

  test('AC-003: 桌面侧栏与 760px 抽屉中长名称不撑出容器，点击目录准确导航', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.goto('/')

    // 1. 桌面视口测试 (1200x800)
    await page.setViewportSize({ width: 1200, height: 800 })
    const acc3Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'gamma-long-address' })
    await expect(acc3Row).toBeVisible({ timeout: 10000 })
    await acc3Row.locator('.tree-disclosure').click()

    const sidebar = page.locator('aside.sidebar')
    const sidebarBox = await sidebar.boundingBox()
    const longEmailSpan = acc3Row.locator('.tree-account-select .tree-label').first()
    const longFolderBtn = acc3Row.locator('.tree-folder-row').filter({ hasText: '超级超长的测试目录名称' })

    await expect(longFolderBtn).toBeVisible()
    const longEmailBox = await longEmailSpan.boundingBox()
    const longFolderBox = await longFolderBtn.boundingBox()

    // 元素右边界不能超出侧边栏右边界
    expect(longEmailBox!.x + longEmailBox!.width).toBeLessThanOrEqual(sidebarBox!.x + sidebarBox!.width + 2)
    expect(longFolderBox!.x + longFolderBox!.width).toBeLessThanOrEqual(sidebarBox!.x + sidebarBox!.width + 2)

    // 2. 点击目录准确导航至该 folder_id
    const acc1Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'alpha@example.com' })
    await acc1Row.locator('.tree-disclosure').click()
    const workFolderBtn = acc1Row.locator('.tree-folder-row').filter({ hasText: '工作邮件' })
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

    const acc1Row = page.locator('.tree-account-block[data-drop-list="master"]').filter({ hasText: 'alpha@example.com' })
    const toggle1 = acc1Row.locator('.tree-disclosure')
    await expect(toggle1).toBeVisible({ timeout: 10000 })

    // 初始 aria-expanded = false
    await expect(toggle1).toHaveAttribute('aria-expanded', 'false')

    // 键盘聚焦并用 Space 展开
    await toggle1.focus()
    await page.keyboard.press('Space')
    await expect(toggle1).toHaveAttribute('aria-expanded', 'true')
    await expect(acc1Row.locator('.tree-folder-list')).toBeVisible()

    // 目录项可通过 Tab 聚焦并按 Enter 导航
    const firstFolder = acc1Row.locator('.tree-folder-row').filter({ hasText: '收件箱' })
    await firstFolder.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('.list-title').getByText('收件箱')).toBeVisible()

    // 键盘 Space 再次折叠
    await toggle1.focus()
    await page.keyboard.press('Enter')
    await expect(toggle1).toHaveAttribute('aria-expanded', 'false')
    await expect(acc1Row.locator('.tree-folder-list')).not.toBeVisible()
  })

  test('t027: 固定 24px 层级、三区独立折叠、760px 断点与双主题保持布局', async ({ page }) => {
    await setupStubApi(page, {
      authedInitially: true,
      groups: [{ id: 'group-layout', name: '自定义组', color: null, sort_order: 0 }],
      accounts: accounts.map((account) => ({ ...account, group_id: account.id === 'acc-1' ? 'group-layout' : null })),
      folderStatsByAccount,
    })
    await page.setViewportSize({ width: 1200, height: 850 })
    await page.goto('/')
    const sidebar = page.locator('aside.sidebar')
    const group = page.locator('.tree-group-block[data-group-id="group-layout"]')
    const member = page.locator('.tree-account-block[data-drop-list="group:group-layout"][data-account-id="acc-1"]')
    const masterAccount = page.locator('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')
    await expect(group).toBeVisible({ timeout: 10000 })
    await expect(masterAccount).toBeVisible()

    const sections = await sidebar.locator('.tree-section').evaluateAll((nodes) => nodes.map((node) => {
      const header = node.querySelector('.tree-section-heading, .tree-group-heading')
      return header?.textContent?.trim().replace(/\s+/g, ' ') || ''
    }))
    expect(sections[0]).toContain('所有账号')
    expect(sections[1]).toContain('自定义组')
    expect(sections[2]).toContain('账号列表')

    const globalSection = sidebar.locator('.tree-section').nth(0)
    const groupSection = sidebar.locator('.tree-section').nth(1)
    const accountSection = sidebar.locator('.tree-section').nth(2)
    await globalSection.getByRole('button', { name: '所有账号' }).click()
    await expect(globalSection.locator('.tree-category-row')).toHaveCount(0)
    await expect(group.locator('.tree-group-heading')).toBeVisible()
    await group.locator('.tree-disclosure').click()
    await expect(group.locator('.tree-group-children')).toBeVisible()
    await accountSection.getByRole('button', { name: '账号列表' }).click()
    await expect(accountSection.locator('.tree-account-list')).toHaveCount(0)
    await expect(group.locator('.tree-group-children')).toBeVisible()

    await globalSection.getByRole('button', { name: '所有账号' }).click()
    const globalCategoryIndent = await globalSection.locator('.tree-category-heading').first().evaluate((node) => getComputedStyle(node).paddingLeft)
    expect(globalCategoryIndent).toBe('24px')
    await globalSection.getByRole('button', { name: '展开 所有收件箱' }).click()
    const nestedCategoryAccountIndent = await globalSection.locator('.tree-category-account').first().evaluate((node) => getComputedStyle(node).paddingLeft)
    expect(nestedCategoryAccountIndent).toBe('48px')
    await accountSection.getByRole('button', { name: '账号列表' }).click()
    const accountIndent = await masterAccount.locator('.tree-account-row').evaluate((node) => getComputedStyle(node).paddingLeft)
    expect(accountIndent).toBe('24px')
    await masterAccount.locator('.tree-disclosure').click()
    const folderIndent = await masterAccount.locator('.tree-folder-row').first().evaluate((node) => getComputedStyle(node).paddingLeft)
    expect(folderIndent).toBe('48px')
    const accountTextBox = await masterAccount.locator('.tree-account-select .tree-label').boundingBox()
    const folderTextBox = await masterAccount.locator('.tree-folder-row .tree-label').first().boundingBox()
    expect(Math.abs(accountTextBox!.x - folderTextBox!.x)).toBeLessThanOrEqual(3)

    await page.getByRole('button', { name: '设置' }).click()
    await page.getByRole('button', { name: '外观' }).click()
    await page.getByRole('button', { name: 'light', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.getByRole('button', { name: 'dark', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.getByRole('button', { name: '关闭' }).click()

    await page.setViewportSize({ width: 761, height: 850 })
    await expect(sidebar).toBeVisible()
    await expect(page.getByRole('button', { name: '打开导航' })).toHaveCount(0)
    await page.setViewportSize({ width: 760, height: 850 })
    await expect(sidebar).toBeHidden()
    await page.getByRole('button', { name: '打开导航' }).click()
    await expect(sidebar).toBeVisible()
  })
})
