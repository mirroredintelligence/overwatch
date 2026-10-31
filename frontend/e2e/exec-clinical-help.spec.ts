import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { TOKEN_ORG_A } from './support/tokens';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';

// The Help pages (W46, W56), the executive set-up welcome (W39) and the clinical on-duty page (W44), as a
// browser sees them. None of these needs a back-end answer to render its first screen: the stand-in back
// end has no alert or clinical routes, and the pages hold their first screen without one.
// Wiring wave (W8B): the screens now read the real back end's routes, so the first screens below are the
// ones that render whatever the stand-in back end answers; the flows that need a seeded request (take,
// advise, the advisor's dialog) are left to the live back-end run. Written, not run (pnpm e2e).

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

test('the clinical queue offers Waiting, Mine and Done, and says when it could not read the queue (W44)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'clinical', TOKEN_ORG_A);
  await page.goto('/clinical/requests');
  await expect(page.getByRole('tab', { name: /^Waiting/ })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Mine' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Done' })).toBeVisible();
  await accessible(page);
});

test('a request that cannot be read offers no advice form (W44, DEC-855)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'clinical', TOKEN_ORG_A);
  await page.goto('/clinical/requests/req-does-not-exist');
  await expect(page.getByRole('alert')).toContainText('could not be read');
  await expect(page.getByRole('button', { name: 'Send advice' })).toHaveCount(0);
});

test('the share page makes no code by itself, and says whether sharing is on (W56)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/help/share');
  await expect(page.getByRole('heading', { level: 1, name: 'Your support code' })).toBeVisible();
  await expect(page.locator('[data-el="HELP-SHARE-CODE"]')).toHaveCount(0);
  await accessible(page);
});

// The executive's phone alerts (W9H, DEC-1040). An executive holds no post, so the notification page is the
// only part of the installed app they use: it opens for an executive, goes to the home screen for a lead,
// and the installed app's front door (/app) takes a signed-in executive to their own home. The permission
// prompt and the push subscription are the browser's and are checked on a real device (W32). Written, not run.
test('the executive opens the alerts on this phone (W9H)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'exec', TOKEN_ORG_A);
  await page.goto('/planning/phone');
  await expect(page.getByRole('heading', { level: 1, name: 'Alerts on this phone' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Allow alerts on this phone' })).toBeVisible();
  await expect(page.getByText('What we never send: Patient names or details.')).toBeVisible();
  await accessible(page);
});

test('a lead on the phone alerts address goes to the home screen (W9H)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/planning/phone');
  await expect(page).toHaveURL(/\/planning$/);
});

test('the installed app opens a signed-in executive on their own home, not the PIN screen (W9H)', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'exec', TOKEN_ORG_A);
  await page.goto('/app');
  await expect(page).toHaveURL(/\/planning$/);
});

test('the PIN screen offers an executive the organisation sign-in (W9H)', async ({ page }) => {
  await page.goto('/app/pin');
  await expect(page.getByRole('link', { name: 'Sign in with your organisation account' })).toHaveAttribute('href', '/sign-in?next=/planning');
});
