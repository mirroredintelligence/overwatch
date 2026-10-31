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

// DEC-1310: the owner's home is the landing at /criteria (the old /owner/criteria had no page).
test('the owner’s landing lists the services, goes straight to a single one, and says so when there are none', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'owner', TOKEN_ORG_A, ['s1', 's2']);
  await page.goto('/criteria');
  await expect(page.getByRole('heading', { level: 1, name: 'Your services' })).toBeVisible();
  await expect(page.getByRole('link', { name: 's2' })).toHaveAttribute('href', '/criteria/s2');
  await expect(page.getByRole('banner').getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/criteria');
  const listed = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(listed.violations).toEqual([]);

  await signIn(page.context(), BASE_URL, 'owner', TOKEN_ORG_A, ['s1']);
  await page.goto('/criteria');
  await expect(page).toHaveURL(/\/criteria\/s1$/);

  await signIn(page.context(), BASE_URL, 'owner', TOKEN_ORG_A, []);
  await page.goto('/criteria');
  await expect(page.getByText('No services to review')).toBeVisible();
  await expect(page.getByRole('main').getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
  const empty = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(empty.violations).toEqual([]);
});

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
