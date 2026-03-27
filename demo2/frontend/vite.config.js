import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/** 与 backend Flask 默认端口一致；preview 也必须代理，否则 /api 会 404 */
const API_TARGET = process.env.VITE_API_PROXY || 'http://127.0.0.1:5000'

const apiProxy = {
  '/api': {
    target: API_TARGET,
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
})
