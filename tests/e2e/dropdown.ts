import type { Locator, Page } from '@playwright/test'

export async function chooseDropdownOption(page: Page, trigger: Locator, value: string) {
  await trigger.click()
  await page.locator(`[data-select-open="true"] [data-option-value="${value}"]`).click()
}
