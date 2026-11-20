/** Single source of truth for CSS media-query breakpoints. */
export const BREAKPOINTS = {
  mobile: 760,
  compact: 900,
  wide: 1180,
  settings: 1100,
} as const

export const MOBILE_MAX_WIDTH = BREAKPOINTS.mobile
