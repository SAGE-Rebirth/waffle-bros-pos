import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In Docker the built screens are served by nginx (frontend/nginx.conf). The dev server below is
// what `make dev` runs: it forwards /api to the backend (the `api` container, or :4000 locally).
const apiTarget = process.env.WB_API_URL || 'http://localhost:4000';

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1200 },
  server: {
    host: true,
    port: 5173,
    // Polling picks up edits made on a Mac through the Docker bind mount.
    watch: process.env.WB_POLL ? { usePolling: true, interval: 300 } : undefined,
    proxy: { '/api': { target: apiTarget, xfwd: true } },
  },
});
