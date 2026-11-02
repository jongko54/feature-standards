import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const password = 'correct-horse-battery-staple';
const freshPassword = 'a-new-long-password-for-reset';

function mail(recipient: string, kind: string): string {
  const directory = mkdtempSync(resolve(tmpdir(), 'fs-browser-mail-'));
  try {
    const output = resolve(directory, 'mail.jsonl');
    const result = spawnSync('uv', ['run', '--frozen', '--project', 'tools', 'python', 'tools/mail_capture.py', '--output', output], {
      cwd: root, env: process.env, encoding: 'utf8', timeout: 15_000,
    });
    expect(result.status, 'private local mail capture must succeed').toBe(0);
    const messages = readFileSync(output, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
    const message = messages.find(item => item.recipient === recipient && item.kind === kind);
    expect(Boolean(message), 'expected private mail capability').toBe(true);
    return message.url;
  } finally { rmSync(directory, { recursive: true, force: true }); }
}

test('별도 가입·메일 확인·로그인·재설정으로 기존 세션을 폐기한다', async ({ page, context }) => {
  const email = `browser-${crypto.randomUUID()}@example.com`;
  await page.goto('/register');
  await page.getByLabel('이메일', { exact: true }).fill(email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '가입 요청', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('요청을 접수했습니다.');
  await page.goto(mail(email, 'verify'));
  await expect(page).toHaveURL(/\/verify-email$/);
  await page.getByRole('button', { name: '이메일 확인', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('이메일을 확인했습니다.');
  await page.goto('/');
  await page.getByLabel('이메일', { exact: true }).fill(email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByTestId('session-email')).toHaveText(email);
  const old = (await context.cookies()).find(cookie => cookie.name === 'fs_session');
  expect(Boolean(old)).toBe(true);
  await page.goto('/forgot-password');
  await page.getByLabel('이메일', { exact: true }).fill(email);
  await page.getByRole('button', { name: '재설정 메일 요청' }).click();
  await expect(page.getByRole('status')).toContainText('요청을 접수했습니다.');
  await page.goto(mail(email, 'reset'));
  await expect(page).toHaveURL(/\/reset-password$/);
  await page.getByLabel('새 비밀번호').fill(freshPassword);
  await page.getByRole('button', { name: '비밀번호 변경' }).click();
  await expect(page.getByRole('status')).toContainText('기존 세션을 종료했습니다.');
  expect((await page.request.get('/auth/me', { headers: { Cookie: `fs_session=${old!.value}` } })).status()).toBe(401);
  await page.goto('/');
  await page.getByLabel('이메일', { exact: true }).fill(email);
  await page.getByLabel('비밀번호', { exact: true }).fill(freshPassword);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByTestId('session-email')).toHaveText(email);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
});

test('확인 링크는 자동 소비하지 않고 클릭한 뒤 재사용을 거절한다', async ({ page }) => {
  const email = `scanner-${crypto.randomUUID()}@example.com`;
  await page.goto('/register');
  await page.getByLabel('이메일', { exact: true }).fill(email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '가입 요청', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('요청을 접수했습니다.');
  const link = mail(email, 'verify');
  let posts = 0;
  page.on('request', request => { if (request.url().endsWith('/auth/email-verification/confirm')) posts++; });
  await page.goto(link);
  await expect(page.getByRole('button', { name: '이메일 확인', exact: true })).toBeEnabled();
  await page.waitForTimeout(100);
  expect(posts).toBe(0);
  await page.getByRole('button', { name: '이메일 확인', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('이메일을 확인했습니다.');
  await page.goto(link);
  await page.getByRole('button', { name: '이메일 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('링크가 유효하지 않거나 만료');
});

test('모바일 가입 입력 오류를 표시하고 페이지가 넘치지 않는다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/register');
  await page.getByLabel('이메일', { exact: true }).fill('한@example.com');
  await page.getByLabel('비밀번호', { exact: true }).fill('short');
  await page.getByRole('button', { name: '가입 요청', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('15자 이상');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel('비밀번호', { exact: true }).fill('');
  if (process.env.FEATURE_STANDARDS_ACCOUNT_SCREENSHOT) await page.screenshot({ path: process.env.FEATURE_STANDARDS_ACCOUNT_SCREENSHOT });
});
