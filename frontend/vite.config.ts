import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const base = process.env.VITE_BASE ?? '/';
const backendTarget = process.env.VITE_BACKEND_TARGET ?? 'http://localhost:666';
// In dev, proxy both the canonical subpath (e.g. /my-panel/api/) and the bare /api/
// so developers can run `VITE_BASE=/my-panel/ vite` without a real nginx in front.
const apiPrefix = base.replace(/\/$/, '') + '/api';

export default defineConfig({
  base,
  plugins: [react()],
  server: {
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
  },
});
