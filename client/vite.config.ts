import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Ports 8000 and 8002 may be occupied by legacy local services during
  // migration. The current development backend is standardized on 8003;
  // deployments
  // remain same-origin on port 8000 inside Docker.
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8003'

  return {
    plugins: [vue()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
