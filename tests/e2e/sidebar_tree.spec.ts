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

  test('p043: 分组和总账号搜索独立工作，并在窄侧栏与移动抽屉内保持可用', async ({ page }) => {
    await setupStubApi(page, {
      authedInitially: true,
      groups: [
        { id: 'group-finance', name: 'Finance', sort_order: 0 },
        { id: 'group-archive', name: 'Archive', sort_order: 1 },
      ],
      accounts: [
        { id: 'acc-finance', email: 'alpha@finance.example', group_id: 'group-finance', provider: 'imap', sync_enabled: true },
        { id: 'acc-archive', email: 'beta@archive.example', group_id: 'group-archive', provider: 'imap', sync_enabled: true },
        { id: 'acc-master', email: 'records@master.example', provider: 'imap', sync_enabled: true },
      ],
      folderStatsByAccount,
    })
    await page.addInitScript(() => {
      localStorage.setItem('mail-ui-storage', JSON.stringify({ state: { sidebarWidth: 180 }, version: 0 }))
    })
    await page.setViewportSize({ width: 1200, height: 800 })
    await page.goto('/')

    const sidebar = page.locator('aside.sidebar')
    const financeSearchButton = page.getByRole('button', { name: '搜索分组 Finance' })
    await expect(financeSearchButton).toBeVisible({ timeout: 10000 })
    await financeSearchButton.click()
    const financeInput = page.getByRole('searchbox', { name: '搜索分组账号：Finance' })
    await expect(financeInput).toBeFocused()
    await financeInput.fill('alpha')
    await expect(page.locator('[data-group-id="group-finance"] .tree-account-block[data-account-id="acc-finance"]')).toBeVisible()
    const sidebarBox = await sidebar.boundingBox()
    const financeInputBox = await financeInput.boundingBox()
    expect(sidebarBox).not.toBeNull()
    expect(financeInputBox!.x + financeInputBox!.width).toBeLessThanOrEqual(sidebarBox!.x + sidebarBox!.width + 1)

    await financeInput.press('Escape')
    await expect(financeInput).toHaveCount(0)
    await page.getByRole('button', { name: '搜索账号列表' }).click()
    const masterInput = page.getByRole('searchbox', { name: '搜索账号列表' })
    await masterInput.fill('beta')
    await expect(page.locator('.tree-account-list .tree-account-block[data-account-id="acc-archive"]')).toBeVisible()
    await expect(page.locator('.tree-account-list .tree-account-block[data-account-id="acc-master"]')).toHaveCount(0)
    const globalSection = page.locator('.tree-section').filter({ has: page.locator('[data-ui="SB12"]') })
    await globalSection.getByRole('button', { name: '展开 所有收件箱' }).click()
    await expect(globalSection.locator('.tree-category-account')).toHaveCount(3)

    await page.reload()
    await expect(page.getByRole('button', { name: '搜索账号列表' })).toBeVisible()
    await expect(page.getByRole('searchbox', { name: '搜索账号列表' })).toHaveCount(0)

    await page.setViewportSize({ width: 375, height: 667 })
    await page.getByRole('button', { name: '打开导航' }).click()
    await expect(sidebar).toBeVisible()
    await page.getByRole('button', { name: '搜索分组 Archive' }).click()
    const drawerInput = page.getByRole('searchbox', { name: '搜索分组账号：Archive' })
    await expect(drawerInput).toBeFocused()
    const drawerBox = await sidebar.boundingBox()
    const drawerInputBox = await drawerInput.boundingBox()
    expect(drawerBox).not.toBeNull()
    expect(drawerInputBox!.x + drawerInputBox!.width).toBeLessThanOrEqual(drawerBox!.x + drawerBox!.width + 1)
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
    // t044 已修复：原 t027 断言未缩进的旧语义（accountTextBox.x 与 folderTextBox.x 相同）已由 t044 严格 24px 阶梯缩进测试替代，移除旧断言

    await page.getByRole('button', { name: '设置' }).click()
    await page.getByRole('button', { name: '通用' }).click()
    await page.getByRole('button', { name: '亮色', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.getByRole('button', { name: '深色', exact: true }).click()
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

  test('t032 AC-001/AC-002: 网页宽屏标题按钮常驻，完整隐藏侧栏后可原位恢复', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/?shell=desktop')

    const sidebar = page.locator('aside.sidebar')
    const toggle = page.getByTestId('sidebar-toggle')
    await expect(toggle).toBeVisible()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(sidebar).toBeVisible()
    expect(await page.evaluate(() => 'kkmailDesktop' in window)).toBe(false)
    await expect(page.getByTestId('mac-titlebar-controls')).toHaveCount(0)

    const toggleBox = await toggle.boundingBox()
    const titleBox = await page.locator('.list-title').boundingBox()
    expect(toggleBox).not.toBeNull()
    expect(titleBox).not.toBeNull()
    expect(Math.abs(toggleBox!.y - titleBox!.y)).toBeLessThanOrEqual(4)

    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(sidebar).toHaveCount(0)
    await expect(toggle).toBeFocused()
    const collapsedColumns = await page.locator('.workspace').evaluate((node) => getComputedStyle(node).gridTemplateColumns)
    expect(collapsedColumns.startsWith('48px')).toBe(false)

    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(sidebar).toBeVisible()
    await expect(toggle).toBeFocused()

    await page.getByRole('button', { name: '设置' }).click()
    const settingsToggle = page.getByTestId('sidebar-toggle')
    await expect(settingsToggle).toHaveAttribute('aria-expanded', 'true')
    await settingsToggle.click()
    await expect(settingsToggle).toHaveAttribute('aria-expanded', 'false')
    await expect(page.locator('aside.sidebar')).toHaveCount(0)
    await settingsToggle.click()
    await expect(settingsToggle).toHaveAttribute('aria-expanded', 'true')
    await expect(page.locator('aside.sidebar')).toBeVisible()
  })

  test('t032 AC-006: 抽屉关闭恢复焦点，跨 760px 时移动与桌面状态分开', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.setViewportSize({ width: 375, height: 720 })
    await page.goto('/')

    const sidebar = page.locator('aside.sidebar')
    const toggle = page.getByTestId('sidebar-toggle')
    const backdrop = page.getByTestId('drawer-backdrop')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(sidebar).toBeVisible()
    await expect(backdrop).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(backdrop).toHaveCount(0)
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(toggle).toBeFocused()

    await toggle.click()
    await backdrop.click({ position: { x: 350, y: 200 } })
    await expect(backdrop).toHaveCount(0)
    await expect(toggle).toBeFocused()

    await toggle.click()
    await page.getByRole('button', { name: '所有收件箱', exact: true }).click()
    await expect(backdrop).toHaveCount(0)
    await expect(toggle).toBeFocused()

    await toggle.click()
    await page.setViewportSize({ width: 761, height: 720 })
    await expect(backdrop).toHaveCount(0)
    await expect(sidebar).toBeVisible()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await page.setViewportSize({ width: 760, height: 720 })
    await expect(sidebar).toBeHidden()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.click()
    await expect(sidebar).toBeVisible()
    await expect(backdrop).toBeVisible()

    await page.setViewportSize({ width: 761, height: 720 })
    await expect(backdrop).toHaveCount(0)
    await expect(sidebar).toHaveCount(0)
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(toggle).toBeFocused()
  })

  test('t032 AC-004: macOS 登录与会话检查期间保留原生标题栏拖动区域', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'kkmailDesktop', { value: { platform: 'darwin' }, configurable: true })
    })
    await setupStubApi(page, { authedInitially: false, accounts, folderStatsByAccount })
    await page.goto('/')

    await expect(page.getByText('登录密码')).toBeVisible()
    await expect(page.getByTestId('mac-login-drag-region')).toBeVisible()
    await expect(page.getByTestId('sidebar-toggle')).toHaveCount(0)
  })

  test('t032 AC-007: 首次绘制前采用已保存主题，系统主题变化保持同步', async ({ page }) => {
    await setupStubApi(page, { authedInitially: true, accounts, folderStatsByAccount })
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.route((url) => new URL(url).pathname === '/', async (route) => {
      const response = await route.fetch()
      const html = await response.text()
      await route.fulfill({
        response,
        body: html.replace('</head>', '<script>window.__themeBeforeApp = document.documentElement.dataset.theme</script></head>'),
      })
    })
    await page.addInitScript(() => {
      localStorage.setItem('mail-ui-storage', JSON.stringify({ state: { theme: 'light' }, version: 0 }))
    })
    await page.goto('/')
    expect(await page.evaluate(() => (window as Window & { __themeBeforeApp?: string }).__themeBeforeApp)).toBe('light')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await expect(page.getByTestId('sidebar-toggle')).toHaveCSS('color', 'rgb(104, 106, 112)')

    await page.getByRole('button', { name: '设置' }).click()
    await page.getByRole('button', { name: '通用' }).click()
    await page.getByRole('button', { name: '深色', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect(page.getByTestId('sidebar-toggle')).toHaveCSS('color', 'rgb(142, 142, 147)')

    await page.getByRole('button', { name: '跟随系统', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })

  test('t044 AC-001 ~ AC-004: 侧边栏顶层标题、子层级与状态提示像素级几何对齐与阶梯缩进', async ({ page }) => {
    await setupStubApi(page, {
      authedInitially: true,
      groups: [{ id: 'group-1', name: '工作分组', color: null, sort_order: 0 }],
      accounts: [
        { id: 'acc-1', email: 'user1@example.com', provider: 'imap', sync_state: 'idle', sync_enabled: true, group_id: 'group-1' },
        { id: 'acc-2', email: 'user2@example.com', provider: 'imap', sync_state: 'idle', sync_enabled: true, group_id: null },
      ],
      folderStatsByAccount: {
        'acc-1': [
          { folder_id: 'f-1', role: 'inbox', name: '收件箱', total_count: 5, unread_count: 1, remote_id: 'INBOX' },
        ],
        'acc-2': [
          { folder_id: 'f-2', role: 'inbox', name: '收件箱', total_count: 2, unread_count: 0, remote_id: 'INBOX' },
        ],
      },
    })
    await page.setViewportSize({ width: 1200, height: 800 })
    await page.goto('/')

    const sidebar = page.locator('aside.sidebar')
    await expect(sidebar).toBeVisible({ timeout: 10000 })

    // 1. AC-001: 顶层三类标题（所有账号、自定义分组、账号列表）的 chevron、icon、text 水平坐标严格对齐（<= 1px）
    const allAccountsSection = sidebar.locator('.tree-section').nth(0)
    const allAccountsChevron = await allAccountsSection.locator('.tree-disclosure, .tree-disclosure-slot').first().boundingBox()
    const allAccountsIcon = await allAccountsSection.locator('svg').nth(1).boundingBox()
    const allAccountsText = await allAccountsSection.locator('.tree-label').first().boundingBox()

    const groupHeading = sidebar.locator('.tree-group-heading').first()
    const groupChevron = await groupHeading.locator('.tree-disclosure').boundingBox()
    const groupIcon = await groupHeading.locator('.tree-group-select svg').first().boundingBox()
    const groupText = await groupHeading.locator('.tree-group-select .tree-label').boundingBox()

    const accountListSection = sidebar.locator('.tree-section').nth(2)
    const accountListHeading = accountListSection.locator('.tree-section-heading')
    const accountListChevron = await accountListHeading.locator('.tree-disclosure, .tree-disclosure-slot').first().boundingBox()
    const accountListIcon = await accountListHeading.locator('.tree-heading-main svg').first().boundingBox()
    const accountListText = await accountListHeading.locator('.tree-heading-main .tree-label').boundingBox()

    expect(allAccountsChevron).not.toBeNull()
    expect(groupChevron).not.toBeNull()
    expect(accountListChevron).not.toBeNull()
    expect(Math.abs(allAccountsChevron!.x - groupChevron!.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(allAccountsChevron!.x - accountListChevron!.x)).toBeLessThanOrEqual(1)

    expect(allAccountsIcon).not.toBeNull()
    expect(groupIcon).not.toBeNull()
    expect(accountListIcon).not.toBeNull()
    expect(Math.abs(allAccountsIcon!.x - groupIcon!.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(allAccountsIcon!.x - accountListIcon!.x)).toBeLessThanOrEqual(1)

    expect(allAccountsText).not.toBeNull()
    expect(groupText).not.toBeNull()
    expect(accountListText).not.toBeNull()
    expect(Math.abs(allAccountsText!.x - groupText!.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(allAccountsText!.x - accountListText!.x)).toBeLessThanOrEqual(1)

    // 2. AC-002: 同一缩进层级兄弟节点对齐，子级文件夹与分类下账号形成 24px 阶梯缩进
    // 展开分组查看其子分类与子账号（均为 Level 1）
    await groupHeading.locator('.tree-disclosure').click()
    const groupChildren = sidebar.locator('.tree-group-children')
    await expect(groupChildren).toBeVisible()

    const groupCategory = groupChildren.locator('.tree-category-heading').first()
    const groupCategoryChevron = await groupCategory.locator('.tree-disclosure').boundingBox()
    const groupCategoryIcon = await groupCategory.locator('.tree-nav-row svg').first().boundingBox()
    const groupCategoryText = await groupCategory.locator('.tree-label').first().boundingBox()

    const groupAccount = groupChildren.locator('.tree-account-row').first()
    const groupAccountChevron = await groupAccount.locator('.tree-disclosure').boundingBox()
    const groupAccountIcon = await groupAccount.locator('.account-dot').boundingBox()
    const groupAccountText = await groupAccount.locator('.tree-label').boundingBox()

    expect(groupCategoryChevron).not.toBeNull()
    expect(groupAccountChevron).not.toBeNull()
    expect(Math.abs(groupCategoryChevron!.x - groupAccountChevron!.x)).toBeLessThanOrEqual(1)

    expect(groupCategoryIcon).not.toBeNull()
    expect(groupAccountIcon).not.toBeNull()
    expect(Math.abs(groupCategoryIcon!.x - groupAccountIcon!.x)).toBeLessThanOrEqual(1)

    expect(groupCategoryText).not.toBeNull()
    expect(groupAccountText).not.toBeNull()
    expect(Math.abs(groupCategoryText!.x - groupAccountText!.x)).toBeLessThanOrEqual(1)

    // 展开组内账号查看文件夹（Level 2）
    await groupAccount.locator('.tree-disclosure').click()
    const folderRow = groupChildren.locator('.tree-folder-row').first()
    await expect(folderRow).toBeVisible()
    const folderIcon = await folderRow.locator('svg').first().boundingBox()
    const folderText = await folderRow.locator('.tree-label').boundingBox()

    expect(folderIcon).not.toBeNull()
    expect(folderText).not.toBeNull()
    expect(folderIcon!.x).toBeGreaterThan(groupAccountIcon!.x)
    expect(Math.abs((folderIcon!.x - groupAccountIcon!.x) - 24)).toBeLessThanOrEqual(1)
    expect(Math.abs((folderText!.x - groupAccountText!.x) - 24)).toBeLessThanOrEqual(1)

    // 展开组内分类查看分类下账号（Level 2）
    await groupCategory.locator('.tree-disclosure').click()
    const categoryAccount = groupChildren.locator('.tree-category-account').first()
    await expect(categoryAccount).toBeVisible()
    const categoryAccountIcon = await categoryAccount.locator('.account-dot').boundingBox()
    const categoryAccountText = await categoryAccount.locator('.tree-label').boundingBox()

    expect(categoryAccountIcon).not.toBeNull()
    expect(categoryAccountText).not.toBeNull()
    expect(categoryAccountIcon!.x).toBeGreaterThan(groupCategoryIcon!.x)
    expect(Math.abs((categoryAccountIcon!.x - groupCategoryIcon!.x) - 24)).toBeLessThanOrEqual(1)
    expect(Math.abs((categoryAccountText!.x - groupCategoryText!.x) - 24)).toBeLessThanOrEqual(1)

    // Level 2 兄弟项水平对齐
    expect(Math.abs(folderIcon!.x - categoryAccountIcon!.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(folderText!.x - categoryAccountText!.x)).toBeLessThanOrEqual(1)

    // 3. AC-003: 内联新建/重命名分组表单、加载状态与错误提示左内边距对齐所属层级
    await sidebar.locator('button[aria-label="新建分组"]').click()
    const newGroupForm = sidebar.locator('.tree-groups-section .tree-inline-form')
    await expect(newGroupForm).toBeVisible()
    const formPaddingLeft = await newGroupForm.evaluate((node) => getComputedStyle(node).paddingLeft)
    expect(formPaddingLeft).toBe('4px')

    const loadingPaddingLeft = await page.evaluate(() => {
      const el = document.createElement('div')
      el.className = 'tree-loading'
      document.body.appendChild(el)
      const pl = getComputedStyle(el).paddingLeft
      el.remove()
      return pl
    })
    expect(loadingPaddingLeft).toBe('24px')

    const folderStatusPaddingLeft = await page.evaluate(() => {
      const el = document.createElement('div')
      el.className = 'tree-folder-status'
      document.body.appendChild(el)
      const pl = getComputedStyle(el).paddingLeft
      el.remove()
      return pl
    })
    expect(folderStatusPaddingLeft).toBe('48px')

    // 4. AC-004: aria-expanded 与键盘交互验证
    const allAccountsBtn = allAccountsSection.locator('.tree-disclosure, .tree-heading-main').first()
    expect(await allAccountsBtn.getAttribute('aria-expanded')).toBe('true')
    await allAccountsBtn.focus()
    await page.keyboard.press('Space')
    expect(await allAccountsBtn.getAttribute('aria-expanded')).toBe('false')
  })
})
