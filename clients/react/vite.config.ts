import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'AUTH_');
  const target = process.env.AUTH_API_TARGET ?? env.AUTH_API_TARGET ?? 'http://127.0.0.1:8000';
  const proxy = {
    '/auth': { target, changeOrigin: false },
    '/healthz': { target, changeOrigin: false },
  };
  return {
    plugins: [react()],
    server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  };
});
