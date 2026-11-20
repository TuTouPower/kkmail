import { expect, type Page } from '@playwright/test'

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
