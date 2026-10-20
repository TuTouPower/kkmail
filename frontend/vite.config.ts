import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Dev-only bridge to mail-core FastAPI (default :8000). Flask stays on :5000.
      '/mail-core': {
        target: process.env.MAIL_CORE_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/mail-core/, ''),
      },
    },
  },
})
