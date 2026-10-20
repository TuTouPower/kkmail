import { useSyncExternalStore } from 'react'

/** Matches the CSS breakpoint where the sidebar becomes an overlay drawer. */
export const MOBILE_MAX_WIDTH = 760

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
