import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { SITE_URL } from './support/env';
import { signIn } from './support/session';
import { TOKEN_ORG_A, TOKEN_ORG_B } from './support/tokens';

// The network pages as a browser sees them (TEN-068 to TEN-071, W17, W43, TEN-082). Written in the build wave
// and not run there: the verification run executes it (pnpm e2e). The browser stand-in
// (e2e/support/network.ts) serves one network, of which organisation A's token is a member and every other
// token is not.

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa'];
const PAGES = ['/network/board', '/network/services', '/network/services/lst-0001', '/network/history', '/network/system-now', '/network/phones'];

test('a member reads the network board: the heading, the scope, the read-only note and a tile for each service', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/network/board');
  await expect(page.getByRole('heading', { level: 1, name: 'Sample Network capacity' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Which board you are viewing' })).toContainText('Showing: Network, Sample Network');
  await expect(page.getByText('You cannot book or change these services from here. Phone the service to check.')).toBeVisible();
  await expect(page.locator('[data-el="NET-BOARD-TILE"]')).toHaveCount(4);
  await expect(page.getByText('Not available on the network. Phone to confirm.')).toBeVisible();
});

test('the network board offers no booking, no "I phoned" and no "They declined"', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/network/board');
  await expect(page.locator('[data-el="NET-BOARD-TILE"]').first()).toBeVisible();
  for (const word of ['Request booking', 'I phoned', 'They declined']) await expect(page.getByText(word)).toHaveCount(0);
});

test('the address of a network page names no network, tenant or scope', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/network/board');
  await expect(page.locator('[data-el="NET-BOARD-TILE"]').first()).toBeVisible();
  expect(page.url()).not.toMatch(/net-|tenant|scope|network[A-Za-z]*=/i);
});

test('a person whose organisation is not a member reads "Network view not available" and no figure', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_B);
  await page.goto('/network/board');
  await expect(page.getByText('Network view not available')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Back to our organisation' })).toHaveAttribute('href', '/advisor/board');
  await expect(page.locator('[data-el="NET-BOARD-TILE"]')).toHaveCount(0);
});

test('the organisation filter works in place and the list view shows the same services', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/network/board');
  await page.getByRole('button', { name: 'Sample Area B' }).click();
  await expect(page.locator('[data-el="NET-BOARD-TILE"]')).toHaveCount(2);
  await page.getByRole('button', { name: 'List' }).click();
  await expect(page.locator('[data-el="NET-BOARD-ROW"]')).toHaveCount(2);
  await page.getByRole('button', { name: 'All organisations' }).click();
  await expect(page.locator('[data-el="NET-BOARD-ROW"]')).toHaveCount(4);
});

test('the advisor’s own board says which board it is, and offers the network', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/advisor/board');
  await expect(page.getByRole('region', { name: 'Which board you are viewing' })).toContainText('Showing: Our organisation');
  await page.getByRole('link', { name: 'Network' }).click();
  await expect(page).toHaveURL(/\/network\/board$/);
});

test('the wall, a wall’s scope header says it is the organisation’s own and offers no switch', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'wall', TOKEN_ORG_A);
  await page.goto('/screen');
  await expect(page.getByRole('region', { name: 'Which board you are viewing' })).toContainText('Showing: Our organisation');
  await expect(page.getByRole('navigation', { name: 'Choose the board' })).toHaveCount(0);
});

test('the wall and the reporter are kept off the network pages', async ({ page }) => {
  for (const role of ['wall', 'reporter']) {
    await signIn(page.context(), SITE_URL, role, TOKEN_ORG_A);
    await page.goto('/network/board');
    await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible();
  }
});

test('the week is for an executive and a shift lead, and withholds nothing it is given to show', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
  await page.goto('/network/week');
  await expect(page.getByRole('heading', { level: 1, name: 'Sample Network this week' })).toBeVisible();
  await expect(page.getByText('No per-member breakdown is shown.')).toBeVisible();
  await expect(page.getByText('Not shown: fewer than 10.').first()).toBeVisible();
});

test('the directory lists the services and a service opens its detail with its criteria', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  await page.goto('/network/services');
  await expect(page.locator('[data-el="NET-SERVICES-ROW"]')).toHaveCount(2);
  await page.getByRole('link', { name: 'UCR West' }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Criteria' })).toBeVisible();
  await expect(page.getByText('Accepts: Frailty, Wound care')).toBeVisible();
});

for (const path of PAGES) {
  test(`${path} passes axe`, async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
    await page.goto(path);
    await expect(page.getByRole('region', { name: 'Which board you are viewing' })).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    expect(results.violations).toEqual([]);
  });
}
