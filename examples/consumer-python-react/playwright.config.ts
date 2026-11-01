import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests', workers: 1, timeout: 30000,
  use: { baseURL: process.env.BASE_URL ?? 'http://127.0.0.1:5174' }, reporter: 'list' });
