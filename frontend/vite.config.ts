import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
//
// `server.proxy` targets the same backend `README.md` tells an operator to start
// (default 127.0.0.1:8420) so `npm run dev` composes with the real API without CORS setup --
// override with PANEL_DEV_PROXY_TARGET if the backend is bound elsewhere.
const proxyTarget = process.env.PANEL_DEV_PROXY_TARGET ?? 'http://127.0.0.1:8420'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
    },
  },
})
