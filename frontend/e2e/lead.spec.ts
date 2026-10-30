import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// The shift lead's pages as a browser sees them (W17, W18, W42, W43, W47). Written in the build wave and not
// run there: the verification run executes it (pnpm e2e). Until the back end has the overview, the lead
// page must say it could not load, and must never say that nothing needs chasing (H-330).

test('an advisor is kept off the shift lead page', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/lead');
  await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible();
});

test('the shift lead page says it could not load, and does not say nothing needs chasing', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead');
  await expect(page.getByRole('alert')).toContainText('We could not load the shift lead page.');
  await expect(page.getByText('No services need chasing.')).toHaveCount(0);
});

test('the shift lead page passes axe once it has answered', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead');
  await expect(page.getByRole('alert')).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
});

test('the audit replay reads as no record for a reference that is not one', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead/audit/%2E%2E%2Fadmin');
  await expect(page.getByRole('alert')).toContainText('No record for that reference.');
});
