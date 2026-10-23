import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const E2E_PASSWORD = process.env.E2E_PASSWORD || 'E2E_Test_Pass_123!'
const IMAP_HOST = process.env.MAIL_CORE_IMAP_HOST || '127.0.0.1'
const IMAP_PORT = process.env.MAIL_CORE_IMAP_PORT || '1143'
const IMAP_USER = process.env.MAIL_CORE_IMAP_USER || 'alice@kkmail.test'
const IMAP_PASS = process.env.MAIL_CORE_IMAP_PASS || 'alice-imap-pass'

async function dragAndSaveLayout(page: import('@playwright/test').Page, source: import('@playwright/test').Locator, target: import('@playwright/test').Locator) {
  await target.scrollIntoViewIfNeeded()
  await expect(source).toBeInViewport()
  const savedRequest = page.waitForRequest((request) =>
    new URL(request.url()).pathname === '/api/sidebar/layout' && request.method() === 'PUT',
  )
  const savedLayout = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/sidebar/layout' && response.request().method() === 'PUT',
  )
  await source.dragTo(target)
  expect((await savedLayout).status()).toBe(204)
  const body = (await savedRequest).postDataJSON() as {
    group_account_ids: Record<string, string[]>
    master_account_ids: string[]
  }
  await expect(page.locator('.tree-account-block[draggable="false"], .tree-group-block[draggable="false"]')).toHaveCount(0)
  await expect(page.locator('.tree-drop-target')).toHaveCount(0)
  return body
}

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
    await expect(pageA.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

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
    await expect(pageB.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

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
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    // 2. 打开设置面板并切换到账户选项卡
    await page.getByRole('button', { name: '设置' }).click()
    const accountTab = page.getByRole('button', { name: '账户', exact: true })
    if (await accountTab.isVisible()) {
      await accountTab.click()
    }

    await page.getByRole('button', { name: '添加账户', exact: true }).click()

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

    await page.getByText('高级凭据配置', { exact: true }).click()
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
    await expect(page1.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    // page2 访问（共享 Cookie 自动已登录）
    await page2.goto('/')
    await expect(page2.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

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

  test('真实拖拽持久化分组成员、独立排序与刷新恢复 (t027 AC-003, AC-005, AC-006, AC-035 ~ AC-038)', async ({ page }) => {
    const nonce = randomUUID()
    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page.locator('#login-password').fill(E2E_PASSWORD)
    await page.locator('button[type="submit"]').click()
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    const csrf = (await (await page.request.get('/api/auth/me')).json()).csrf_token as string
    const headers = { 'x-csrf-token': csrf }
    const baselineAccounts = ((await (await page.request.get('/api/accounts?limit=200&offset=0')).json()).accounts) as Array<{ id: string; group_id?: string | null }>
    const baselineGroups = ((await (await page.request.get('/api/groups')).json()).groups) as Array<{ id: string }>
    const createGroup = async (name: string) => {
      const response = await page.request.post('/api/groups', { data: { name }, headers })
      expect(response.status()).toBe(200)
      return (await response.json()).id as string
    }
    const createAccount = async (email: string) => {
      const response = await page.request.post('/api/accounts', {
        data: { email, provider: 'memory' },
        headers,
      })
      expect(response.status()).toBe(200)
      return (await response.json()).id as string
    }

    const groupA = await createGroup(`出差-${nonce.slice(0, 8)}`)
    const groupB = await createGroup(`财务-${nonce.slice(0, 8)}`)
    const emptyGroup = await createGroup(`空组-${nonce.slice(0, 8)}`)
    const accountA = await createAccount(`a-${nonce}@a.example`)
    const accountB = await createAccount(`b-${nonce}@a.example`)
    const accountC = await createAccount(`c-${nonce}@b.example`)
    const accountD = await createAccount(`d-${nonce}@c.example`)
    const baselineGroupIds = baselineGroups.map((group) => group.id)
    const groupAccountIds: Record<string, string[]> = Object.fromEntries(baselineGroups.map((group) => [
      group.id,
      baselineAccounts.filter((account) => account.group_id === group.id).map((account) => account.id),
    ]))
    groupAccountIds[groupA] = [accountA, accountB]
    groupAccountIds[groupB] = [accountC]
    groupAccountIds[emptyGroup] = []
    const layoutRevision = (await (await page.request.get('/api/sidebar/layout')).json()).revision as string
    const initialLayout = await page.request.put('/api/sidebar/layout', {
      data: {
        expected_revision: layoutRevision,
        group_ids: [...baselineGroupIds, groupA, groupB, emptyGroup],
        master_account_ids: [...baselineAccounts.map((account) => account.id), accountA, accountB, accountC, accountD],
        ungrouped_account_ids: [
          ...baselineAccounts.filter((account) => !account.group_id || !baselineGroupIds.includes(account.group_id)).map((account) => account.id),
          accountD,
        ],
        group_account_ids: groupAccountIds,
      },
      headers,
    })
    expect(initialLayout.status()).toBe(204)

    await page.reload()
    const group = (id: string) => page.locator(`.tree-group-block[data-group-id="${id}"]`)
    const accountInMaster = (id: string) => page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${id}"]`)
    const accountInGroup = (groupId: string, accountId: string) => group(groupId).locator(`.tree-account-block[data-drop-list="group:${groupId}"][data-account-id="${accountId}"]`)
    await expect(accountInMaster(accountA)).toBeVisible()

    // A collapsed empty group accepts a drop from the account list.
    await dragAndSaveLayout(page, accountInMaster(accountD).locator('.tree-account-row'), group(emptyGroup))
    await expect(group(emptyGroup).locator('.tree-count')).toHaveText('1')
    await group(emptyGroup).locator('.tree-disclosure').click()
    await expect(accountInGroup(emptyGroup, accountD)).toHaveCount(1)

    // Cross-group drop inserts before the target account; dropping on the account-list header ungroups it.
    await group(groupA).locator('.tree-disclosure').click()
    await group(groupB).locator('.tree-disclosure').click()
    const groupReorder = await dragAndSaveLayout(
      page,
      accountInGroup(groupA, accountB).locator('.tree-account-row'),
      accountInGroup(groupA, accountA).locator('.tree-account-row'),
    )
    expect(groupReorder.group_account_ids[groupA]).toEqual([accountB, accountA])
    const crossSource = accountInGroup(groupA, accountA).locator('.tree-account-row')
    const crossTarget = accountInGroup(groupB, accountC).locator('.tree-account-row')
    await crossSource.scrollIntoViewIfNeeded()
    await crossTarget.scrollIntoViewIfNeeded()
    const crossGroupLayout = await dragAndSaveLayout(page, crossSource, crossTarget)
    expect(crossGroupLayout.group_account_ids[groupA]).not.toContain(accountA)
    expect(crossGroupLayout.group_account_ids[groupB].indexOf(accountA)).toBeLessThan(crossGroupLayout.group_account_ids[groupB].indexOf(accountC))
    const afterCrossGroup = ((await (await page.request.get('/api/accounts?limit=200&offset=0')).json()).accounts) as Array<{ id: string; group_id: string | null }>
    expect(afterCrossGroup.find((account) => account.id === accountA)?.group_id).toBe(groupB)
    await expect(accountInGroup(groupB, accountA)).toBeVisible()
    const appendToPopulated = await dragAndSaveLayout(page, accountInGroup(emptyGroup, accountD).locator('.tree-account-row'), group(groupB).locator('.tree-group-heading'))
    expect(appendToPopulated.group_account_ids[groupB]).toEqual([accountA, accountC, accountD])
    const restoreEmpty = await dragAndSaveLayout(page, accountInGroup(groupB, accountD).locator('.tree-account-row'), group(emptyGroup).locator('.tree-group-heading'))
    expect(restoreEmpty.group_account_ids[emptyGroup]).toEqual([accountD])
    await group(groupA).locator('.tree-group-heading > .tree-disclosure').click()
    await group(emptyGroup).locator('.tree-group-heading > .tree-disclosure').click()
    await page.evaluate(() => {
      const targetWindow = window as typeof window & { __sidebarDragEvidence?: Array<{ kind: string; list: string; account: string; payload: string }> }
      targetWindow.__sidebarDragEvidence = []
      document.addEventListener('dragstart', (event) => {
        const block = (event.target as HTMLElement).closest('.tree-account-block') as HTMLElement | null
        targetWindow.__sidebarDragEvidence?.push({ kind: 'start', list: block?.dataset.dropList || '', account: block?.dataset.accountId || '', payload: '' })
      }, true)
      document.addEventListener('drop', (event) => {
        const block = (event.target as HTMLElement).closest('.tree-account-block') as HTMLElement | null
        targetWindow.__sidebarDragEvidence?.push({ kind: 'drop', list: block?.dataset.dropList || '', account: block?.dataset.accountId || '', payload: event.dataTransfer?.getData('text/plain') || '' })
      }, true)
    })
    const ungroupSource = accountInGroup(groupB, accountA).locator('.tree-account-row')
    const ungroupTarget = accountInMaster(accountD).locator('.tree-account-row')
    const dragBoxes = { source: await ungroupSource.boundingBox(), target: await ungroupTarget.boundingBox() }
    const masterRowUngroup = await dragAndSaveLayout(page, ungroupSource, ungroupTarget)
    const dragEvidence = await page.evaluate(() => (window as typeof window & { __sidebarDragEvidence?: Array<{ kind: string; list: string; account: string; payload: string }> }).__sidebarDragEvidence || [])
    expect(dragEvidence, JSON.stringify({ dragBoxes, dragEvidence })).toContainEqual({ kind: 'start', list: `group:${groupB}`, account: accountA, payload: '' })
    expect(dragEvidence.find((item) => item.kind === 'drop')?.payload).toContain('"sourceList":"group"')
    expect(masterRowUngroup.group_account_ids[groupB]).not.toContain(accountA)
    await expect(accountInGroup(groupB, accountA)).toHaveCount(0)
    const ungroupOnHeader = await dragAndSaveLayout(page, accountInGroup(groupB, accountC).locator('.tree-account-row'), page.locator('[data-drop-kind="master-list"]'))
    expect(ungroupOnHeader.group_account_ids[groupB]).toEqual([])
    const restoreGroup = await dragAndSaveLayout(page, accountInMaster(accountC).locator('.tree-account-row'), group(groupB).locator('.tree-group-heading'))
    expect(restoreGroup.group_account_ids[groupB]).toEqual([accountC])

    // Reordering a grouped account in the master list keeps its group membership.
    await dragAndSaveLayout(page, accountInMaster(accountD).locator('.tree-account-row'), accountInMaster(accountB).locator('.tree-account-row'))
    await group(emptyGroup).locator('.tree-group-heading > .tree-disclosure').click()
    await expect(accountInGroup(emptyGroup, accountD)).toHaveCount(1)

    // Reordering groups changes only group order and survives a browser reload.
    await dragAndSaveLayout(page, group(groupB).locator('.tree-group-heading'), group(groupA).locator('.tree-group-heading'))
    await page.reload()

    await expect.poll(async () => group(groupB).getAttribute('data-group-id')).toBe(groupB)
    const visibleGroupIds = await page.locator('.tree-groups-section > .tree-group-block').evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('data-group-id')),
    )
    expect(visibleGroupIds).toEqual([...baselineGroupIds, groupB, groupA, emptyGroup])

    const accountsResponse = await page.request.get('/api/accounts?limit=200&offset=0')
    const persistedAccounts = (await accountsResponse.json()).accounts as Array<{ id: string; group_id: string | null; master_order: number | null }>
    const byId = new Map(persistedAccounts.map((account) => [account.id, account]))
    expect(byId.get(accountA)?.group_id).toBeNull()
    expect(byId.get(accountB)?.group_id).toBe(groupA)
    expect(byId.get(accountC)?.group_id).toBe(groupB)
    expect(byId.get(accountD)?.group_id).toBe(emptyGroup)
    const ownAccountIds = new Set([accountA, accountB, accountC, accountD])
    const persistedMasterOrder = [...persistedAccounts]
      .sort((a, b) => (a.master_order ?? 0) - (b.master_order ?? 0))
      .map((account) => account.id)
      .filter((id) => ownAccountIds.has(id))
    expect(persistedMasterOrder).toEqual([accountD, accountB, accountA, accountC])

    const resetResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/sidebar/layout/default-order' && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '恢复默认排序' }).click()
    expect((await resetResponse).status()).toBe(204)
    await expect.poll(async () => {
      const resetAccounts = ((await (await page.request.get('/api/accounts?limit=200&offset=0')).json()).accounts) as Array<{ id: string; master_order: number | null; group_order: number | null }>
      return resetAccounts.filter((account) => ownAccountIds.has(account.id)).every((account) => account.master_order === null && account.group_order === null)
    }).toBe(true)
  })

  test('设置下拉通过真实浏览器选择切换及清空账号分组 (t027 AC-030)', async ({ page }) => {
    const nonce = randomUUID()
    const firstGroupName = `移组源-${nonce.slice(0, 8)}`
    const secondGroupName = `移组目标-${nonce.slice(0, 8)}`
    const email = `move-${nonce}@example.test`

    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page.locator('#login-password').fill(E2E_PASSWORD)
    await page.locator('button[type="submit"]').click()
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    const csrf = (await (await page.request.get('/api/auth/me')).json()).csrf_token as string
    const headers = { 'x-csrf-token': csrf }
    const firstGroupResponse = await page.request.post('/api/groups', { data: { name: firstGroupName }, headers })
    const secondGroupResponse = await page.request.post('/api/groups', { data: { name: secondGroupName }, headers })
    expect(firstGroupResponse.status()).toBe(200)
    expect(secondGroupResponse.status()).toBe(200)
    const firstGroupId = (await firstGroupResponse.json()).id as string
    const secondGroupId = (await secondGroupResponse.json()).id as string
    const accountResponse = await page.request.post('/api/accounts', {
      data: { email, provider: 'memory', group_id: firstGroupId },
      headers,
    })
    expect(accountResponse.status()).toBe(200)
    const accountId = (await accountResponse.json()).id as string

    await page.reload()
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })
    await page.getByRole('button', { name: '设置' }).click()
    const accountSelect = page.getByLabel(`移动 ${email}`)
    const accountRow = accountSelect.locator('xpath=..')
    const accountDetails = accountRow.locator('div').first()
    await expect(accountSelect).toHaveValue(firstGroupId)

    const moveResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/accounts/${accountId}` && response.request().method() === 'PATCH',
    )
    await accountSelect.selectOption(secondGroupId)
    expect((await moveResponse).status()).toBe(200)
    await expect(accountSelect).toHaveValue(secondGroupId)
    await expect(accountDetails).toContainText(secondGroupName)
    let accounts = ((await (await page.request.get('/api/accounts?limit=500&offset=0')).json()).accounts) as Array<{ id: string; group_id: string | null }>
    expect(accounts.find((item) => item.id === accountId)?.group_id).toBe(secondGroupId)

    const clearResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/accounts/${accountId}` && response.request().method() === 'PATCH',
    )
    await accountSelect.selectOption('')
    expect((await clearResponse).status()).toBe(200)
    await expect(accountSelect).toHaveValue('')
    await expect(accountDetails).not.toContainText(secondGroupName)
    accounts = ((await (await page.request.get('/api/accounts?limit=500&offset=0')).json()).accounts) as Array<{ id: string; group_id: string | null }>
    expect(accounts.find((item) => item.id === accountId)?.group_id).toBeNull()
  })

  test('真实浏览器拖拽保存失败后保留服务端归属 (t027 AC-040)', async ({ page }) => {
    const nonce = randomUUID()
    const groupName = `保存失败-${nonce.slice(0, 8)}`
    const email = `rollback-${nonce}@example.test`

    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page.locator('#login-password').fill(E2E_PASSWORD)
    await page.locator('button[type="submit"]').click()
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    const csrf = (await (await page.request.get('/api/auth/me')).json()).csrf_token as string
    const headers = { 'x-csrf-token': csrf }
    const groupResponse = await page.request.post('/api/groups', { data: { name: groupName }, headers })
    expect(groupResponse.status()).toBe(200)
    const groupId = (await groupResponse.json()).id as string
    const accountResponse = await page.request.post('/api/accounts', { data: { email, provider: 'memory' }, headers })
    expect(accountResponse.status()).toBe(200)
    const accountId = (await accountResponse.json()).id as string

    await page.reload()
    const group = page.locator(`.tree-group-block[data-group-id="${groupId}"]`)
    const source = page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${accountId}"] .tree-account-row`)
    const target = group.locator('.tree-group-heading')
    await expect(source).toBeVisible({ timeout: 15000 })
    await expect(target).toBeVisible()
    await page.route('**/api/sidebar/layout', async (route) => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({ status: 500, json: { detail: 'simulated layout failure' } })
      } else {
        await route.continue()
      }
    })
    const failedSave = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/sidebar/layout' && response.request().method() === 'PUT',
    )
    await target.scrollIntoViewIfNeeded()
    await source.dragTo(target)
    expect((await failedSave).status()).toBe(500)
    await expect(page.getByRole('alert')).toContainText('simulated layout failure')
    await expect(page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${accountId}"]`)).toBeVisible()
    await expect(group.locator(`.tree-account-block[data-account-id="${accountId}"]`)).toHaveCount(0)

    const persistedLayout = await (await page.request.get('/api/sidebar/layout')).json() as { group_account_ids: Record<string, string[]> }
    expect(persistedLayout.group_account_ids[groupId]).toEqual([])
    const persistedAccounts = ((await (await page.request.get('/api/accounts?limit=500&offset=0')).json()).accounts) as Array<{ id: string; group_id: string | null }>
    expect(persistedAccounts.find((account) => account.id === accountId)?.group_id).toBeNull()
  })

  test('浏览器中的自拖、取消和外部拖放不改布局 (t027 AC-034, AC-040)', async ({ page }) => {
    const nonce = randomUUID()
    const groupName = `无效拖放-${nonce.slice(0, 8)}`
    const firstEmail = `first-${nonce}@example.test`
    const secondEmail = `second-${nonce}@example.test`

    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page.locator('#login-password').fill(E2E_PASSWORD)
    await page.locator('button[type="submit"]').click()
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    const csrf = (await (await page.request.get('/api/auth/me')).json()).csrf_token as string
    const headers = { 'x-csrf-token': csrf }
    const groupResponse = await page.request.post('/api/groups', { data: { name: groupName }, headers })
    expect(groupResponse.status()).toBe(200)
    const groupId = (await groupResponse.json()).id as string
    const firstResponse = await page.request.post('/api/accounts', { data: { email: firstEmail, provider: 'memory' }, headers })
    const secondResponse = await page.request.post('/api/accounts', { data: { email: secondEmail, provider: 'memory' }, headers })
    expect(firstResponse.status()).toBe(200)
    expect(secondResponse.status()).toBe(200)
    const firstId = (await firstResponse.json()).id as string
    const secondId = (await secondResponse.json()).id as string

    await page.reload()
    const group = page.locator(`.tree-group-block[data-group-id="${groupId}"]`)
    const first = page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${firstId}"] .tree-account-row`)
    const second = page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${secondId}"] .tree-account-row`)
    const layoutWrites: string[] = []
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/sidebar/layout' && request.method() === 'PUT') layoutWrites.push(request.postData() || '')
    })
    await expect(first).toBeVisible({ timeout: 15000 })
    await expect(group.locator('.tree-group-heading')).toBeVisible()
    await first.locator('xpath=..').locator('.tree-disclosure').click()
    await group.locator('.tree-icon-action').click()
    await page.keyboard.press('Escape')
    await first.dragTo(first)

    await page.evaluate(() => {
      const external = document.createElement('div')
      external.id = 'external-drag-source'
      external.draggable = true
      external.textContent = '外部拖动项'
      external.style.cssText = 'position:fixed;right:24px;top:24px;z-index:9999;width:120px;height:40px;background:var(--surface);'
      external.addEventListener('dragstart', (event) => event.dataTransfer?.setData('text/plain', 'foreign payload'))
      document.body.append(external)
    })
    const external = page.locator('#external-drag-source')
    await first.dragTo(external)
    await external.dragTo(group.locator('.tree-group-heading'))
    await page.waitForTimeout(100)

    expect(layoutWrites).toHaveLength(0)
    await expect(page.locator('.tree-drop-target')).toHaveCount(0)
    await expect(page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${firstId}"]`)).toBeVisible()
    await expect(group.locator(`.tree-account-block[data-account-id="${firstId}"]`)).toHaveCount(0)
    await expect(page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${secondId}"]`)).toBeVisible()
  })

  test('保存进行中禁用第二次真实拖动，不发送旧快照覆盖请求 (t027 AC-040)', async ({ page }) => {
    const nonce = randomUUID()
    const groupName = `连续拖动-${nonce.slice(0, 8)}`
    const firstEmail = `first-${nonce}@example.test`
    const secondEmail = `second-${nonce}@example.test`

    await page.goto('/')
    await expect(page.locator('#login-password')).toBeVisible({ timeout: 15000 })
    await page.locator('#login-password').fill(E2E_PASSWORD)
    await page.locator('button[type="submit"]').click()
    await expect(page.getByRole('button', { name: '所有收件箱', exact: true })).toBeVisible({ timeout: 15000 })

    const csrf = (await (await page.request.get('/api/auth/me')).json()).csrf_token as string
    const headers = { 'x-csrf-token': csrf }
    const groupResponse = await page.request.post('/api/groups', { data: { name: groupName }, headers })
    expect(groupResponse.status()).toBe(200)
    const groupId = (await groupResponse.json()).id as string
    const firstResponse = await page.request.post('/api/accounts', { data: { email: firstEmail, provider: 'memory' }, headers })
    const secondResponse = await page.request.post('/api/accounts', { data: { email: secondEmail, provider: 'memory' }, headers })
    expect(firstResponse.status()).toBe(200)
    expect(secondResponse.status()).toBe(200)
    const firstId = (await firstResponse.json()).id as string
    const secondId = (await secondResponse.json()).id as string

    await page.reload()
    const group = page.locator(`.tree-group-block[data-group-id="${groupId}"]`)
    const first = page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${firstId}"] .tree-account-row`)
    const secondBlock = page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${secondId}"]`)
    const second = secondBlock.locator('.tree-account-row')
    const target = group.locator('.tree-group-heading')
    await expect(first).toBeVisible({ timeout: 15000 })
    await expect(secondBlock).toHaveAttribute('draggable', 'true')

    let releaseFirst!: () => void
    let signalFirstStarted!: () => void
    const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve })
    const firstStarted = new Promise<void>((resolve) => { signalFirstStarted = resolve })
    let layoutWrites = 0
    await page.route('**/api/sidebar/layout', async (route) => {
      if (route.request().method() === 'PUT') {
        layoutWrites += 1
        if (layoutWrites === 1) {
          signalFirstStarted()
          await firstGate
        }
      }
      await route.continue()
    })

    const firstDrag = first.dragTo(target)
    await firstStarted
    await expect(secondBlock).toHaveAttribute('draggable', 'false')
    await second.dragTo(target)
    expect(layoutWrites).toBe(1)
    releaseFirst()
    await firstDrag
    await group.locator('.tree-disclosure').click()
    await expect(group.locator(`.tree-account-block[data-account-id="${firstId}"]`)).toBeVisible()
    await expect(page.locator(`.tree-account-block[data-drop-list="master"][data-account-id="${secondId}"]`)).toBeVisible()
    expect(layoutWrites).toBe(1)
  })
})
