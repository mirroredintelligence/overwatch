import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('wall screen shows its heading and a page title', async ({ page }) => {
  await page.goto('/screen');

  await expect(
    page.getByRole('heading', { name: 'DIUCS capacity wall screen' }),
  ).toBeVisible();
  await expect(page).toHaveTitle(/DIUCS capacity/);
});

test('wall screen passes axe including colour contrast in a real browser', async ({
  page,
}) => {
  await page.goto('/screen');

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();

  expect(results.violations).toEqual([]);
});
