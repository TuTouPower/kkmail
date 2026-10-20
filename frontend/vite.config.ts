import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiTarget = process.env.MAIL_CORE_PROXY_TARGET || 'http://127.0.0.1:8000'

// Dev server proxies the mail-core API so the SPA stays same-origin (session cookie + CSRF).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/health': { target: apiTarget },
      '/ready': { target: apiTarget },
    },
  },
})
