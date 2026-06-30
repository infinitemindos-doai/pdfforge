import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// pdfforge web — Vite config
// Dev: proxy /api → localhost:8000 (FastAPI)
// Prod: VITE_API_URL env var points to Render backend

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})