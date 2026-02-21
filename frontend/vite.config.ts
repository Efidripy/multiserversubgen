import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const base = process.env.VITE_BASE ?? '/';
// In dev, proxy both the canonical subpath (e.g. /my-vpn/api/) and the bare /api/
// so developers can run `VITE_BASE=/my-vpn/ vite` without a real nginx in front.
const apiPrefix = base.replace(/\/$/, '') + '/api';

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    proxy: {
      [apiPrefix]: {
        target: 'http://localhost:666',
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