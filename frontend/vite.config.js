import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The FastAPI backend serves frontend/dist in production and listens on :4000.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1200 },
  server: { host: true, port: 5173, proxy: { '/api': 'http://localhost:4000' } },
});
