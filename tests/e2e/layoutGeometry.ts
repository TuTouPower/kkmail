import { expect, type Locator, type Page } from '@playwright/test'

type Rect = { x: number; y: number; width: number; height: number }

export async function setNarrowViewport(page: Page, width = 360, height = 640): Promise<void> {
  await page.setViewportSize({ width, height })
}

export function rectsOverlap(a: Rect, b: Rect): boolean {
  const aRight = a.x + a.width
  const bRight = b.x + b.width
  const aBottom = a.y + a.height
  const bBottom = b.y + b.height
  return a.x < bRight && b.x < aRight && a.y < bBottom && b.y < aBottom
}

/** Shared narrow-screen horizontal-overflow gate for iframe/scroll containers. */
export async function assertNoHorizontalOverflow(locator: Locator): Promise<void> {
  const metrics = await locator.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }))
  expect(
    metrics.scrollWidth,
    `horizontal overflow: scrollWidth=${metrics.scrollWidth}, clientWidth=${metrics.clientWidth}`,
  ).toBeLessThanOrEqual(metrics.clientWidth + 1)
}

/** Shared narrow-screen geometry gate. Reused by reader toolbar and mail body specs. */
export async function assertNoOverlap(page: Page, selectorA: string, selectorB: string): Promise<void> {
  const locatorA = page.locator(selectorA).first()
  const locatorB = page.locator(selectorB).first()
  await expect(locatorA).toBeVisible()
  await expect(locatorB).toBeVisible()
  const boxA = await locatorA.boundingBox()
  const boxB = await locatorB.boundingBox()
  expect(boxA, `${selectorA} has no bounding box`).not.toBeNull()
  expect(boxB, `${selectorB} has no bounding box`).not.toBeNull()
  expect(rectsOverlap(boxA as Rect, boxB as Rect), `${selectorA} overlaps ${selectorB}`).toBe(false)
}
