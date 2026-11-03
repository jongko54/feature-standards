import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './profile-tests', workers: 1, timeout: 60000,
  outputDir: process.env.CONSUMER_CAPTURE_DIR ? `${process.env.CONSUMER_CAPTURE_DIR}/browser-results` : './test-results',
  use: { baseURL: process.env.BASE_URL ?? 'http://127.0.0.1:5175', trace: 'off', screenshot: 'off', video: 'off' },
  reporter: 'list',
});
