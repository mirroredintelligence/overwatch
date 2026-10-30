import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

// The public pages of wave 6 (W52 tour, W53 lessons and practice) in a browser, with axe (WCAG 2.2 A
// and AA). Written in the build wave and not run there; the verification run executes it (pnpm e2e).
// The practice pages must make no request that sends anything: only the page's own load is allowed.

test('the tour starts, and its practice step answers without a request', async ({ page }) => {
  await page.goto('/tour');
  await expect(page.getByRole('heading', { level: 1, name: 'Less chasing. Faster answers.' })).toBeVisible();
  await page.getByRole('button', { name: 'Take the 1-minute tour' }).click();
  await page.getByRole('button', { name: 'I report capacity for a service' }).click();
  await page.getByRole('button', { name: 'Continue' }).click();

  const posts: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET') posts.push(request.url());
  });
  await page.goto('/tour?step=practice');
  await page.getByRole('button', { name: 'Yes, still 3' }).click();
  await expect(page.getByText('Practice done')).toBeVisible();
  expect(posts).toEqual([]);

  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze();
  expect(results.violations).toEqual([]);
});

test('the lessons library and a lesson load, and practice mode says nothing is sent', async ({ page }) => {
  await page.goto('/learn');
  await expect(page.getByRole('heading', { level: 1, name: '2-minute lessons' })).toBeVisible();
  await page.goto('/learn/correct-a-figure');
  await expect(page.getByRole('heading', { level: 1, name: /Correct a figure/ })).toBeVisible();
  await page.goto('/learn/correct-a-figure/practice');
  await expect(page.getByText('Practice. Nothing is sent.')).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze();
  expect(results.violations).toEqual([]);
});
