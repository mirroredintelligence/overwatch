import { expect, test } from '@playwright/test';

// The root page, the same for every host: the product name, the page language and nothing about a
// place or an organisation (TEN-045). The wall screen needs a paired session, so it is covered by
// board.spec.ts and live.spec.ts.

test('the root page names the product and no place', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle('DIUCS capacity');
  await expect(page.getByRole('heading', { level: 1, name: 'DIUCS capacity' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-GB');
  expect(await page.locator('body').innerText()).not.toMatch(/dorset|trust|spoa|single point/i);
});

test('the root page has a neutral description', async ({ page }) => {
  await page.goto('/');

  const description = await page.locator('meta[name="description"]').getAttribute('content');
  expect(description).toBeTruthy();
  expect(description).not.toMatch(/dorset|trust|spoa|single point/i);
});

test('the wall screen sends an unpaired browser to pairing, with a title that names no organisation', async ({ page }) => {
  await page.goto('/screen');

  await expect(page).toHaveURL(/\/screen\/pair$/);
});
