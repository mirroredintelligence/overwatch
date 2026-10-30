import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { TOKEN_ORG_A } from './support/tokens';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';

// The Help pages (W46, W56), the executive set-up welcome (W39) and the clinical on-duty page (W44), as a
// browser sees them. None of these needs a back-end answer to render its first screen: the stand-in back
// end has no alert or clinical routes, and the pages hold their first screen without one.
// Written in the build wave and not run there; the verification run executes it (pnpm e2e).

const BASE_URL = SITE_URL;

async function accessible(page: import('@playwright/test').Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}

test('Help offers the safety concern and the problem report, and the share link is always there (W46, W56)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/help');
  await expect(page.getByRole('heading', { level: 1, name: 'Help' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Report a safety concern' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Share my session with support' })).toHaveAttribute('href', '/help/share');
  await accessible(page);
});

test('the safety concern form shows its warning and its categories (W46)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/help/safety');
  await expect(page.getByText('If someone is at risk now, phone the coordination team or follow local procedure first.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Wrong service shown' })).toBeVisible();
  await accessible(page);
});

test('the problem report page takes its kinds (W46)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/help/problem?from=/help');
  await expect(page.getByRole('button', { name: 'A button does not work' })).toBeVisible();
  await accessible(page);
});

test('the executive set-up opens on the welcome (W39)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'exec', TOKEN_ORG_A);
  await page.goto('/planning/setup');
  await expect(page.getByRole('heading', { level: 1, name: 'The whole system in your pocket' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose my alerts' })).toBeVisible();
  await accessible(page);
});

test('the clinical on-duty page asks whether the advisor is taking requests (W44)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'clinical', TOKEN_ORG_A);
  await page.goto('/clinical');
  await expect(page.getByRole('heading', { level: 1, name: 'Are you taking requests?' })).toBeVisible();
  await accessible(page);
});
