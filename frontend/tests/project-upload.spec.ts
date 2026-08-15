import { expect, test } from '@playwright/test';
import path from 'node:path';

test('사용자가 프로젝트와 PDF를 등록하면 queued 상태를 본다', async ({ page }, testInfo) => {
  await page.goto('/');

  await page.getByLabel('프로젝트명').fill('산노리');
  await page.getByRole('button', { name: '프로젝트 생성' }).click();

  await expect(page.getByRole('heading', { name: '산노리' })).toBeVisible();
  await page.getByLabel('원본 파일').setInputFiles(
    path.resolve('tests/fixtures/sample.pdf'),
  );

  await expect(page.getByText('sample.pdf')).toBeVisible();
  await expect(page.getByText('queued', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('queued.png'), fullPage: true });
});
