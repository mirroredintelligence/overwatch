import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// W30, W31: the criteria owner's flow and the second approval. Written in the build wave and not run
// there; the verification run executes it (pnpm e2e). The criteria pages are guarded by role (DEC-700),
// and their values come from the back end, which does not serve them yet (see the W30 fragment). The
// spec checks the guard and the axe rules on each view, and the heading the page always shows.

const BASE_URL = SITE_URL;
const WCAG = ['wcag2a', 'wcag2aa', 'wcag21aa'];

test('an advisor is refused the criteria pages, which were unguarded before W30', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  for (const path of ['/criteria/s1', '/criteria/s1/history', '/criteria/s1/approve']) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(403);
  }
});

test('the owner’s pages pass axe at phone width, and the history names the audit record', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await signIn(page.context(), BASE_URL, 'owner', TOKEN_ORG_A);

  await page.goto('/criteria/sample-service');
  await expect(page.locator('main')).toBeVisible();
  const overview = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(overview.violations).toEqual([]);

  await page.goto('/criteria/sample-service/history');
  await expect(page.getByRole('heading', { level: 1, name: 'History' })).toBeVisible();
  await expect(page.getByText('Every version stays in the audit record.')).toBeVisible();
  const history = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(history.violations).toEqual([]);

  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflows).toBe(false);
});

test('a clinical lead sees the second approval page, and it passes axe', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'clinical', TOKEN_ORG_A);
  await page.goto('/criteria/sample-service/approve');
  await expect(page.locator('main')).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations).toEqual([]);
});
