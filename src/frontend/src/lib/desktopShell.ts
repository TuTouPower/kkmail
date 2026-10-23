/** Read the minimal platform hint exposed by Electron's isolated preload. */
export function getDesktopPlatform(): string | null {
  if (typeof window === 'undefined') return null
  const bridge = (window as Window & { kkmailDesktop?: { platform?: unknown } }).kkmailDesktop
  return typeof bridge?.platform === 'string' ? bridge.platform : null
}
