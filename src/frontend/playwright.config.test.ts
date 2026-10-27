import { afterEach, describe, expect, it, vi } from 'vitest'

// A335: reuseExistingServer must stay off unless explicitly opted in, so a
// stray service already listening on the preview port is never mistaken
// for the freshly built kkmail preview.
async function loadWebServer() {
  // The vitest worker inherits BASE_URL="/" from vite; the config treats a
  // set BASE_URL as "external server" and drops webServer entirely.
  vi.stubEnv('BASE_URL', '')
  vi.resetModules()
  const mod = await import('./playwright.config')
  const config = mod.default as { webServer?: { reuseExistingServer?: boolean } }
  return config.webServer
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('playwright.config webServer reuse (A335)', () => {
  it('does not reuse an existing server by default', async () => {
    vi.stubEnv('CI', '')
    vi.stubEnv('PLAYWRIGHT_REUSE_EXISTING_SERVER', '')
    const webServer = await loadWebServer()
    expect(webServer?.reuseExistingServer).toBe(false)
  }, 30000)

  it('reuses only when PLAYWRIGHT_REUSE_EXISTING_SERVER=1 is set explicitly', async () => {
    vi.stubEnv('CI', '')
    vi.stubEnv('PLAYWRIGHT_REUSE_EXISTING_SERVER', '1')
    const webServer = await loadWebServer()
    expect(webServer?.reuseExistingServer).toBe(true)
  }, 30000)

  it('never reuses in CI even when explicitly requested', async () => {
    vi.stubEnv('CI', 'true')
    vi.stubEnv('PLAYWRIGHT_REUSE_EXISTING_SERVER', '1')
    const webServer = await loadWebServer()
    expect(webServer?.reuseExistingServer).toBe(false)
  }, 30000)
})
