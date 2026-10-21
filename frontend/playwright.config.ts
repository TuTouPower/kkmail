import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  webServer: {
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
        // Prefer local installed chromium or chrome
      },
    },
  ],
})
