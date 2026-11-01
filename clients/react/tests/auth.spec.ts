import { expect, test, type Page } from '@playwright/test';

async function login(page: Page) {
  await page.getByLabel('이메일', { exact: true }).fill('demo@example.com');
  await page.getByLabel('비밀번호', { exact: true }).fill('correct-horse-battery-staple');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByTestId('session-email')).toHaveText('demo@example.com');
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeEnabled();
});

test('로그인, 새로고침 복원, 세션 확인과 로그아웃', async ({ page, context }) => {
  await login(page);
  const cookie = (await context.cookies()).find((candidate) => candidate.name === 'fs_session');
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe('Lax');
  expect(await page.evaluate(() => document.cookie)).not.toContain('fs_session');
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  await page.reload();
  await expect(page.getByTestId('session-email')).toHaveText('demo@example.com');
  await expect(page.getByRole('status')).toHaveText('로그인 상태를 복원했습니다.');
  await page.getByRole('button', { name: '세션 상태 확인' }).click();
  await expect(page.getByRole('status')).toHaveText('세션이 유효합니다.');
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeEnabled();
  await expect(page.getByRole('status')).toHaveText('로그아웃했습니다. 서버 세션이 종료되었습니다.');
  expect((await context.cookies()).some((candidate) => candidate.name === 'fs_session')).toBe(false);
  await page.reload();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeEnabled();
  await expect(page.getByTestId('session-email')).toHaveCount(0);
});

test('잘못된 자격 증명은 일반 오류로 표시하고 키보드로 재시도할 수 있다', async ({ page }) => {
  await page.getByLabel('비밀번호', { exact: true }).fill('incorrect-password');
  await page.getByLabel('비밀번호', { exact: true }).press('Enter');
  await expect(page.getByRole('alert')).toHaveText('이메일 또는 비밀번호를 확인해 주세요.');
  await expect(page.getByTestId('session-email')).toHaveCount(0);
  await login(page);
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('Unicode 이메일을 계약대로 서버에 전달하고 로그인한다', async ({ page }) => {
  const email = '한@example.com';
  const password = 'correct-horse-battery-staple';
  let submitted: unknown;
  await page.route('**/auth/login', async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      json: { user: { id: 'unicode-user', email }, csrfToken: 'test-unicode-csrf-token' },
    });
  });
  const emailInput = page.getByLabel('이메일', { exact: true });
  await emailInput.fill(email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect.poll(() => submitted, {
    message: '계약에서 허용하는 Unicode 이메일이 브라우저 검증에 막히지 않고 제출되어야 한다.',
    timeout: 1500,
  }).toEqual({ email, password });
  await expect(page.getByTestId('session-email')).toHaveText(email);
});

test('로그아웃 거절 시 인증 상태를 보존한다', async ({ page }) => {
  await login(page);
  await page.route('**/auth/logout', (route) => route.fulfill({ status: 403, json: { error: { code: 'CSRF_INVALID', message: 'rejected' } } }));
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('세션 확인 정보가 일치하지 않습니다.');
  await expect(page.getByTestId('session-email')).toHaveText('demo@example.com');
  await page.unroute('**/auth/logout');
  await page.getByRole('button', { name: '세션 상태 확인' }).click();
  await expect(page.getByRole('status')).toHaveText('세션이 유효합니다.');
});

test('상태 조회의 401을 세션 만료로 표시한다', async ({ page }) => {
  await login(page);
  await page.route('**/auth/me', (route) => route.fulfill({ status: 401, json: { error: { code: 'UNAUTHENTICATED', message: 'expired' } } }));
  await page.getByRole('button', { name: '세션 상태 확인' }).click();
  await expect(page.getByRole('status')).toHaveText('세션이 만료되었습니다. 다시 로그인해 주세요.');
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeEnabled();
});

test('네트워크 오류는 로그아웃으로 처리하지 않는다', async ({ page }) => {
  await login(page);
  await page.route('**/auth/me', (route) => route.abort('connectionrefused'));
  await page.getByRole('button', { name: '세션 상태 확인' }).click();
  await expect(page.getByRole('alert')).toContainText('서버에 연결할 수 없습니다.');
  await expect(page.getByTestId('session-email')).toHaveText('demo@example.com');
});

test('429의 대기 시간을 표시하고 종료 후 재시도한다', async ({ page }) => {
  await page.route('**/auth/login', (route) => route.fulfill({ status: 429, headers: { 'Retry-After': '2' }, json: { error: { code: 'RATE_LIMITED', message: 'limited' } } }), { times: 1 });
  await page.getByLabel('비밀번호', { exact: true }).fill('correct-horse-battery-staple');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('로그인 시도가 많습니다.');
  await expect(page.getByRole('button', { name: /초 후 다시 시도/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeEnabled({ timeout: 5000 });
  await login(page);
});

test('모바일 화면에서 가로 넘침 없이 입력과 버튼에 접근한다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: /하나의 규격,\s*같은 로그인 경험\./ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await login(page);
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
