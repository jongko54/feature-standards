import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './account-tests', workers: 1, fullyParallel: false,
  forbidOnly: Boolean(process.env.CI), retries: 0, timeout: 30_000,
  use: { baseURL: process.env.BASE_URL ?? 'http://127.0.0.1:5173', locale: 'ko-KR' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }], reporter: 'list',
});
