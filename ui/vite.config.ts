import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // The backend serves ui/dist at its root, so asset URLs stay relative-to-root.
  base: '/',
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev so geometry fetches and multipart uploads need no CORS dance.
      '/api': { target: 'http://127.0.0.1:8849', changeOrigin: true },
    },
  },
  build: {
    // three's chunk alone is ~520 kB minified (130 kB gzip) and is cached
    // separately; the default 500 kB warning would fire on every build.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // three is most of the bundle and changes far less often than the app;
        // its own chunk keeps it cached across UI rebuilds.
        manualChunks: { three: ['three'] },
      },
    },
  },
})
