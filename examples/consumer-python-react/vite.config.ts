import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.AUTH_API_TARGET ?? 'http://127.0.0.1:8000';
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/auth': { target }, '/api': { target }, '/healthz': { target } } },
});
