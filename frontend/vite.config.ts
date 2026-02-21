import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:666',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../backend/build',
    emptyOutDir: true,
  },
});