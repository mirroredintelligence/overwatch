import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { SITE_URL } from './support/env';
import { signIn } from './support/session';
import { TOKEN_ORG_A } from './support/tokens';

// The support console's insight page (W49, W9F), as a browser sees it: the five tabs read the back end's
// answers (the stand-in serves the shapes the real mappers write), a group under 10 reads "fewer than 10",
// and a person who is not support is turned away. Written, not run (pnpm e2e).

const BASE_URL = SITE_URL;

async function accessible(page: import('@playwright/test').Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}

test('the funnels tab shows the steps with their share and a hidden step as fewer than 10', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'support', TOKEN_ORG_A);
  await page.goto('/console/insight');
  await expect(page.getByRole('heading', { level: 1, name: 'Insight' })).toBeVisible();
  const steps = page.getByRole('list', { name: 'Funnel steps' });
  await expect(steps.getByText('Home-screen guide viewed')).toBeVisible();
  await expect(steps.getByText('fewer than 10')).toBeVisible();
  await accessible(page);
});

test('the friction tab marks an element over 5% with the word Review and says what it hides', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'support', TOKEN_ORG_A);
  await page.goto('/console/insight?tab=friction');
  const table = page.getByRole('table', { name: 'Friction by element table' });
  await expect(table.getByRole('row', { name: /ADV-OPT-REQUEST-BTN/ })).toContainText('Review');
  await expect(page.getByText('1 element or page with fewer than 10 sessions is not shown.')).toBeVisible();
  await accessible(page);
});

test('the performance tab names each vital against its budget in words, by device', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'support', TOKEN_ORG_A);
  await page.goto('/console/insight?tab=performance');
  await page.getByRole('button', { name: 'Phone' }).click();
  await expect(page.getByRole('table', { name: 'Web vitals table' })).toBeVisible();
  await expect(page.getByText('Prompt to board: not measured yet.')).toBeVisible();
  await accessible(page);
});

test('the releases tab compares two releases and shows the pipeline', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'support', TOKEN_ORG_A);
  await page.goto('/console/insight?tab=releases');
  await expect(page.getByText('Comparing 1.4.3 with 1.4.2')).toBeVisible();
  await expect(page.getByRole('table', { name: 'Pipeline health' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Device' })).toHaveCount(0);
  await accessible(page);
});

test('an advisor is turned away from the insight page', async ({ page }) => {
  await signIn(page.context(), BASE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/console/insight');
  await expect(page.getByText('You do not have access to the console.')).toBeVisible();
});
