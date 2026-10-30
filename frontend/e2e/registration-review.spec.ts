import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// W28, W29: the shift lead's scope list and registration review. Written in the build wave and not run
// there; the verification run executes it (pnpm e2e). It checks the guard, the scope list the back end
// serves, and the axe rules on every view. The queue and the review overview answer 503 until the back
// end serves those reads (see the W28 fragment), so those views are checked for their heading only.

const BASE_URL = SITE_URL;
const WCAG = ['wcag2a', 'wcag2aa', 'wcag21aa'];

test('a signed-out visitor to the scope list is sent to sign-in', async ({ page }) => {
  await page.goto('/lead/scope');
  await expect(page).toHaveURL(/\/sign-in\?next=%2Flead%2Fscope/);
});

test('an advisor is refused the scope list with the forbidden page', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  const response = await page.goto('/lead/scope');
  expect(response?.status()).toBe(403);
});

test('the shift lead sees the scope list and it passes axe', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead/scope');
  await expect(page.getByRole('heading', { level: 1, name: 'Services in scope' })).toBeVisible();
  await expect(page.getByText('You can only invite services on this list.')).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations).toEqual([]);
});

test('the registrations queue and one review pass axe on the shift lead’s phone width', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await signIn(page.context(), BASE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead/registrations');
  await expect(page.getByRole('heading', { level: 1, name: 'Registrations' })).toBeVisible();
  const queue = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(queue.violations).toEqual([]);

  await page.goto('/lead/registrations/sample-review?step=scope');
  await expect(page.getByRole('heading', { level: 1, name: 'Is it in scope?' })).toBeVisible();
  const scope = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(scope.violations).toEqual([]);

  // The horizontal page scroll is the phone-width failure: none is allowed at 360 px.
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflows).toBe(false);
});
