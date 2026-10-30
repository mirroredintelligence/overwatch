import { expect, test } from '@playwright/test';

// The root page, the same for every host: the product name, the page language and nothing about a
// place or an organisation (TEN-045). The wall screen needs a paired session, so it is covered by
// board.spec.ts and live.spec.ts.

test('the root page names the product and the organisation of its host, and no other place', async ({ page }) => {
  await page.goto('/');

  // The host's own profile gives the organisation's name (TEN-049); the product follows it.
  await expect(page).toHaveTitle('Sample Area A | DIUCS capacity');
  await expect(page.getByRole('heading', { level: 1, name: 'DIUCS capacity' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-GB');
  expect(await page.locator('body').innerText()).not.toMatch(/dorset|trust|spoa|single point/i);
  // The root page is the same for every host; only the title carries the organisation.
  await expect(page.getByText('Sample Area A')).toHaveCount(0);
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

test('the sign-in page says which organisation it is for, in the organisation’s own words', async ({ page }) => {
  await page.goto('/sign-in');

  await expect(page.getByRole('region', { name: 'Organisation' })).toHaveText('Sample Area A');
  await expect(page.getByRole('button', { name: 'Sign in with your staff account' })).toBeVisible();
});
