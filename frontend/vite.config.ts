import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'AI_QUERY_')
  const target = process.env.AI_QUERY_API_TARGET || env.AI_QUERY_API_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: { host: '127.0.0.1', proxy: { '/api': target } },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react-runtime'
            if (/\/node_modules\/@ant-design\/(cssinjs|cssinjs-utils|fast-color|colors)\//.test(id)) {
              return 'design-styles'
            }
          },
        },
      },
    },
  }
})
