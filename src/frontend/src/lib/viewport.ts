import { useSyncExternalStore } from 'react'
import { MOBILE_MAX_WIDTH } from '../design-system/breakpoints'

export { MOBILE_MAX_WIDTH }

function subscribeResize(onChange: () => void) {
  window.addEventListener('resize', onChange)
  return () => window.removeEventListener('resize', onChange)
}

export function isWideViewport(width = window.innerWidth): boolean {
  return width > MOBILE_MAX_WIDTH
}

export function useIsWide(): boolean {
  return useSyncExternalStore(subscribeResize, () => isWideViewport(), () => true)
}
