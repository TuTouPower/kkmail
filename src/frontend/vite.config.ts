import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const apiTarget = process.env.MAIL_CORE_PROXY_TARGET || 'http://127.0.0.1:8000'

// Dev server proxies the mail-core API so the SPA stays same-origin (session cookie + CSRF).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost/' } },
    setupFiles: ['./src/test/test_setup.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/api/generated/**', 'src/**/*.d.ts'],
      reporter: ['text-summary', 'json', 'lcov'],
      reportsDirectory: '../../.scratch/frontend_coverage',
    },
    exclude: ['e2e/**', '**/node_modules/**'],
  },
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/health': { target: apiTarget },
      '/ready': { target: apiTarget },
    },
  },
})
