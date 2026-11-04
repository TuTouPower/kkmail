export interface ElementBadge {
  id: string
  key: string
  top: number
  left: number
}

const BADGE_WIDTH = 38
const BADGE_HEIGHT = 18

export function resolveBadgePositions(
  rawList: Array<{ id: string; top: number; left: number }>,
  viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1024,
): ElementBadge[] {
  const result: ElementBadge[] = []
  const placed: Array<{ top: number; left: number }> = []

  rawList.forEach((item, index) => {
    let top = item.top
    let left = item.left

    let attempts = 0
    while (attempts < 6) {
      const collision = placed.find(
        (p) => Math.abs(p.top - top) < BADGE_HEIGHT - 2 && Math.abs(p.left - left) < BADGE_WIDTH - 2,
      )
      if (!collision) break
      if (left + BADGE_WIDTH + 4 < viewportWidth - 20) {
        left = collision.left + BADGE_WIDTH + 4
      } else {
        top = collision.top + BADGE_HEIGHT + 2
        left = item.left
      }
      attempts++
    }

    placed.push({ top, left })
    result.push({
      id: item.id,
      key: `${item.id}-${index}`,
      top,
      left,
    })
  })
  return result
}
