import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { test, expect } from '@playwright/test';
import '../tests/consumer.spec';

function capturedLink(email: string, kind: 'verify' | 'reset'): string {
  const root = process.env.CONSUMER_ROOT!;
  const destination = join(process.env.CONSUMER_CAPTURE_DIR!, `${randomUUID()}.jsonl`);
  // The guarded capture tool emits only loopback 5173 links. Rebase their route
  // onto this independent consumer frontend without widening that tool's scope.
  execFileSync('uv', ['run', '--frozen', '--project', join(root, 'tools'), 'python', join(root, 'tools/mail_capture.py'), '--output', destination], { stdio: 'pipe' });
  for (const line of readFileSync(destination, 'utf8').trim().split('\n')) {
    const message = JSON.parse(line);
    if (message.recipient !== email || message.kind !== kind) continue;
    const source = new URL(message.url);
    const expectedPath = kind === 'verify' ? '/verify-email' : '/reset-password';
    if (source.origin !== 'http://127.0.0.1:5173' || source.pathname !== expectedPath || !/^#token=[A-Za-z0-9_-]{43}$/.test(source.hash)) break;
    return new URL(source.pathname + source.hash, process.env.BASE_URL).href;
  }
  throw new Error('Expected a private local consumer capture message');
}

if (process.env.CONSUMER_PROFILE === 'browser-session-v3') {
  test('consumer UI registers, verifies and resets a protected account', async ({ page }) => {
    try {
      const email = `browser-${process.env.CONSUMER_BACKEND}@example.com`;
      const password = 'consumer-browser-original-password';
      const replacement = 'consumer-browser-replacement-password';
      await page.goto('/');
      await page.getByRole('link', { name: 'Register', exact: true }).click();
      await page.getByLabel('Email', { exact: true }).fill(email);
      await page.getByLabel('Password', { exact: true }).fill(password);
      await page.getByRole('button', { name: 'Register', exact: true }).click();
      await expect(page.getByRole('status')).toHaveText('Request accepted. Check your email.');
      await page.getByRole('link', { name: 'Sign in' }).click();
      await page.getByLabel('이메일').fill(email);
      await page.getByLabel('비밀번호').fill(password);
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      await expect(page.getByRole('alert')).toBeVisible();
      await expect(page.getByTestId('profile')).toHaveCount(0);
      await page.goto(capturedLink(email, 'verify'));
      await expect.poll(() => new URL(page.url()).hash).toBe('');
      await page.getByRole('button', { name: 'Verify email', exact: true }).click();
      await expect(page.getByRole('status')).toHaveText('Completed. Sign in to continue.');
      await page.getByRole('link', { name: 'Sign in' }).click();
      await page.getByLabel('이메일').fill(email);
      await page.getByLabel('비밀번호').fill(password);
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      await expect(page.getByTestId('profile')).toContainText(email);
      const session = (await page.context().cookies()).find(cookie => cookie.name === 'fs_session');
      if (!session) throw new Error('Missing consumer browser session');
      const original = await page.request.get('/api/profile');
      expect(original.status()).toBe(200);
      expect((await original.json()).user.email).toBe(email);
      await page.getByRole('link', { name: 'Request reset', exact: true }).click();
      await page.getByLabel('Email', { exact: true }).fill(email);
      await page.getByRole('button', { name: 'Request reset', exact: true }).click();
      await expect(page.getByRole('status')).toHaveText('Request accepted. Check your email.');
      await page.goto(capturedLink(email, 'reset'));
      await expect.poll(() => new URL(page.url()).hash).toBe('');
      await page.getByLabel('New password').fill(replacement);
      await page.getByRole('button', { name: 'Reset password', exact: true }).click();
      await expect(page.getByRole('status')).toHaveText('Completed. Sign in to continue.');
      expect((await page.request.get('/api/profile', { headers: { Cookie: `fs_session=${session.value}` } })).status()).toBe(401);
      await page.getByRole('link', { name: 'Sign in' }).click();
      await page.getByLabel('이메일').fill(email);
      await page.getByLabel('비밀번호').fill(password);
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      await expect(page.getByRole('alert')).toBeVisible();
      await page.getByLabel('비밀번호').fill(replacement);
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      await expect(page.getByTestId('profile')).toContainText(email);
    } catch {
      // No token-bearing navigation URL, cookie, password or driver call log is
      // allowed into failure output. Private captures live only in a temp dir.
      throw new Error('Consumer account browser scenario failed');
    }
  });
}
