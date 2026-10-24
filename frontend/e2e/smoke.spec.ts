import { expect, test } from '@playwright/test';

test('wall screen shows its heading and a page title', async ({ page }) => {
  await page.goto('/screen');

  await expect(
    page.getByRole('heading', { name: 'DIUCS capacity wall screen' }),
  ).toBeVisible();
  await expect(page).toHaveTitle(/DIUCS capacity/);
});
