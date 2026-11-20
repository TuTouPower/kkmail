import { expect, test } from '@playwright/test'
import { createMockMessages, setupStubApi } from './stubApi'
import { assertNoHorizontalOverflow, setNarrowViewport } from './layoutGeometry'

const FIXED_WIDTH_HTML = `
<div style="width:680px;background:#ffffff;color:#111111">
  <table width="680" cellpadding="0" cellspacing="0" style="width:680px">
    <tr><td>
      <h1 style="font-size:32px;margin:0 0 16px">Your weekly Web Analytics summary</h1>
      <p style="font-size:18px">This report includes aggregate visits, page views and unique visitors for your sites so you can monitor their performance over time.</p>
      <table width="680" style="width:680px"><tr><td>Total sites</td><td>Visits</td><td>Bounce rate</td></tr></table>
    </td></tr>
  </table>
</div>`

test('固定宽度 HTML 邮件在 360px 视口不横向溢出', async ({ page }) => {
  const message = {
    ...createMockMessages()[0],
    subject: 'Fixed width weekly report',
    body_html: FIXED_WIDTH_HTML,
  }
  await setupStubApi(page, { authedInitially: true, messages: [message] })

  await setNarrowViewport(page)
  await page.goto('/')
  await expect(page.getByText(message.subject)).toBeVisible({ timeout: 10000 })
  await page.getByText(message.subject).first().click()

  const frame = page.frameLocator('iframe[title="邮件正文"]')
  await expect(frame.locator('h1')).toContainText('Your weekly Web Analytics summary', { timeout: 5000 })
  await assertNoHorizontalOverflow(frame.locator('html'))
  await assertNoHorizontalOverflow(frame.locator('body'))
})
