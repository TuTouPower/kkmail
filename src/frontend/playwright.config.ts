import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright E2E configuration for kkmail.
 * Tests are located in top-level tests/e2e/ directory.
 */
export default defineConfig({
  testDir: '../../tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  outputDir: '../../.scratch/e2e_artifacts',
  use: {
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: 'npm run build && npm run preview -- --port 4173 --host 127.0.0.1',
        port: 4173,
        // A335: never reuse a server by default — whatever already listens
        // on 4173 (stale build, someone else's service) would silently be
        // tested instead of the fresh preview. Opt in explicitly with
        // PLAYWRIGHT_REUSE_EXISTING_SERVER=1; CI never reuses.
        reuseExistingServer:
          !process.env.CI && process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === '1',
        timeout: 30000,
      },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],
})
