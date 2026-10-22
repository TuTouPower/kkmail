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
        reuseExistingServer: !process.env.CI,
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
