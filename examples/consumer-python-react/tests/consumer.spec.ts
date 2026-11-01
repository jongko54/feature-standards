import { test, expect } from '@playwright/test';

test('인증 전 소비 앱 API 접근을 거절한다', async ({ request }) => {
  const response = await request.get('/api/profile');
  expect(response.status()).toBe(401);
});

test('공통 패키지로 로그인·복원·보호 API·로그아웃한다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('비밀번호').fill('correct-horse-battery-staple');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByTestId('profile')).toHaveText('demo-user / demo@example.com');
  await page.reload();
  await expect(page.getByTestId('profile')).toHaveText('demo-user / demo@example.com');
  const session = (await page.context().cookies()).find(cookie => cookie.name === 'fs_session');
  expect(session).toBeDefined();
  await page.getByRole('button', { name: '로그아웃' }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeEnabled();
  expect((await page.request.get('/api/profile')).status()).toBe(401);
  expect((await page.request.get('/api/profile', {
    headers: { Cookie: `fs_session=${session!.value}` },
  })).status()).toBe(401);
});

test('두 번째 사용자는 자기 프로필을 조회한다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('이메일').fill('other@example.com');
  await page.getByLabel('비밀번호').fill('other-correct-horse-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByTestId('profile')).toHaveText('other-user / other@example.com');
});
