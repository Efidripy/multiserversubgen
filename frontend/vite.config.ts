import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const base = process.env.VITE_BASE ?? '/mssg/';
const backendTarget = process.env.VITE_BACKEND_TARGET ?? 'http://localhost:666';
// In dev, proxy both the canonical subpath (e.g. /my-panel/api/) and the bare /api/
// so developers can run `VITE_BASE=/my-panel/ vite` without a real nginx in front.
const apiPrefix = base.replace(/\/$/, '') + '/api';

export default defineConfig({
  base,
  plugins: [react(), tailwindcss()],
  server: {
    allowedHosts: ['host.docker.internal'],
    proxy: {
      [apiPrefix]: {
        target: backendTarget,
        changeOrigin: true,
        rewrite: (path: string) => '/api' + path.slice(apiPrefix.length),
      },
    },
  },
  build: {
    outDir: '../backend/build',
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-i18n': ['i18next', 'react-i18next'],
          'vendor-charts': ['chart.js', 'react-chartjs-2'],
          'vendor-axios': ['axios'],
        },
      },
    },
  },
});
