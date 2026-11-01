import { randomBytes } from 'node:crypto';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { SITE_URL } from './support/env';
import { signInOperator } from './support/operator';
import { OPERATOR_LIVE_PREFIX } from './support/platform';
import { signIn } from './support/session';
import { TOKEN_ORG_A } from './support/tokens';

// The three admin portals in a browser (design canvas "Overwatch admin portals"): the shared frame (logo,
// navigation, who is signed in, sign-out), the real empty states and, end to end against the stand-in back
// end, creating a tenant with a directory id and a group-to-role mapping, seeing it in the list and
// verifying its directory. Each test has its own operator token, so the stand-in keeps each test's tenants
// to itself (e2e/support/platform.ts).

const GROUP_ONE = '11111111-1111-4111-8111-111111111111';
const GROUP_TWO = '22222222-2222-4222-8222-222222222222';
const DIRECTORY = '00000000-0000-4000-8000-000000000000';

const axe = async (page: Page) => (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations;
const liveToken = (kind = 'operator') => `${OPERATOR_LIVE_PREFIX}${kind}-${randomBytes(6).toString('hex')}`;

test.describe('the platform console', () => {
  test('has the frame on every page: the logo, the role in words, the navigation and a sign-out that works', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.goto('/operator');
    await expect(page.getByRole('link', { name: 'Overwatch' })).toHaveAttribute('href', '/operator');
    await expect(page.getByText('Signed in as platform operator')).toBeVisible();
    const nav = page.getByRole('navigation', { name: 'Platform console' });
    await expect(nav.getByRole('link', { name: 'Tenants' })).toHaveAttribute('aria-current', 'page');
    await expect(nav.getByRole('link', { name: 'Audit chain' })).toBeVisible();
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page).toHaveURL(/\/operator\/sign-in/);
  });

  test('says there are no tenants yet, with the one next step, and passes axe', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.goto('/operator');
    await expect(page.getByRole('heading', { level: 2, name: 'There are no tenants yet.' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Create the first tenant' })).toHaveAttribute('href', '/operator/tenants/new');
    expect(await axe(page)).toEqual([]);
  });

  test('gives a support person the same empty state with no way to create a tenant', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'support', liveToken('support'));
    await page.goto('/operator');
    await expect(page.getByRole('heading', { level: 2, name: 'There are no tenants yet.' })).toBeVisible();
    await expect(page.getByText('Signed in as support')).toBeVisible();
    await expect(page.getByRole('link', { name: /Create/ })).toHaveCount(0);
  });

  test('creates a tenant with a directory id and a group-to-role mapping, and it appears in the list', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.goto('/operator');
    await page.getByRole('link', { name: 'Create the first tenant' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Create a tenant' })).toBeVisible();
    expect(await axe(page)).toEqual([]);

    await page.getByLabel('Tenant id').fill('example-trust-e2e');
    await page.getByLabel('Display name').fill('Example Trust E2E');
    await page.getByLabel('Legal name').fill('Example Trust E2E Organisation');
    await page.getByLabel('ODS code').fill('RZZ03');
    await page.getByLabel('Directory id').fill(DIRECTORY);
    await page.getByRole('button', { name: 'Add a group' }).click();
    await page.getByRole('button', { name: 'Add another group' }).click();
    const groups = page.getByLabel('Group object id');
    await groups.nth(0).fill(GROUP_ONE);
    await groups.nth(1).fill(GROUP_TWO);
    await page.getByRole('combobox', { name: 'Role' }).nth(0).selectOption('lead');
    await page.getByRole('combobox', { name: 'Role' }).nth(1).selectOption('advisor');
    expect(await axe(page)).toEqual([]);
    await page.getByRole('button', { name: 'Create tenant' }).click();

    const done = page.getByRole('status');
    await expect(done).toContainText('Tenant created. It is being set up.');
    await expect(done).toContainText('The directory is waiting to be verified.');
    await expect(done).toContainText('2 groups are mapped to roles.');

    await page.goto('/operator');
    const table = page.getByRole('table', { name: 'Tenants' });
    const row = table.getByRole('row', { name: /Example Trust E2E/ });
    await expect(row.getByText('Being set up')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Create a tenant' })).toBeVisible();
    expect(await axe(page)).toEqual([]);

    // The tenant's page shows the directory as waiting and the mapping, and verifying moves it on.
    await row.getByRole('link', { name: 'Example Trust E2E' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Example Trust E2E' })).toBeVisible();
    const directory = page.getByRole('region', { name: 'Directory' });
    await expect(directory.getByText(DIRECTORY)).toBeVisible();
    await expect(directory.getByText('Waiting to be verified')).toBeVisible();
    await expect(directory.getByRole('table', { name: 'Roles by group' }).getByText('Shift lead')).toBeVisible();
    await expect(directory.getByRole('table', { name: 'Roles by group' }).getByText('Advisor')).toBeVisible();
    expect(await axe(page)).toEqual([]);
    await directory.getByRole('button', { name: 'Verify this directory' }).click();
    await expect(directory.getByText('Directory verified.')).toBeVisible();
    await expect(directory.getByText('Verified', { exact: true }).first()).toBeVisible();
    await expect(directory.getByRole('button', { name: 'Verify this directory' })).toHaveCount(0);

    // Admin consent, step 1 (DEC-1316): the Entra administrator is named and emailed; the page shows only the
    // masked address and that the invitation is waiting (it is approved only once the back end sees the app installed).
    const consent = page.getByRole('region', { name: 'Administrator consent' });
    await expect(consent.getByText('No invitation has been sent.')).toBeVisible();
    await consent.getByLabel('Administrator’s work email').fill('jane.admin@example-trust.test');
    await consent.getByRole('button', { name: 'Send consent invitation' }).click();
    await expect(consent.getByText('Invitation emailed.')).toBeVisible();
    await expect(consent.getByText('j***@example-trust.test')).toBeVisible();
    await expect(consent.getByText('Waiting for approval')).toBeVisible();
    await expect(consent.getByRole('button', { name: 'Send again' })).toBeVisible();
    await expect(page.locator('body')).not.toContainText('jane.admin@example-trust.test');
    expect(await axe(page)).toEqual([]);
  });

  test('refuses a directory id that is not a directory id, in words, and creates nothing', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.goto('/operator/tenants/new');
    await page.getByLabel('Tenant id').fill('example-bad-directory');
    await page.getByLabel('Display name').fill('Example Bad Directory');
    await page.getByLabel('Legal name').fill('Example Bad Directory Organisation');
    await page.getByLabel('ODS code').fill('RZZ03');
    await page.getByLabel('Directory id').fill('not-a-guid');
    await page.getByRole('button', { name: 'Create tenant' }).click();
    await expect(page.locator('[data-el="FORM-ERROR-SUMMARY"]')).toContainText('There is 1 problem');
    await expect(page.getByRole('link', { name: /Directory id: enter it as a directory id/ })).toHaveAttribute('href', '#directory-id');
    expect(await axe(page)).toEqual([]);
    await page.goto('/operator');
    await expect(page.getByRole('heading', { level: 2, name: 'There are no tenants yet.' })).toBeVisible();
  });

  test('reads as cards on a phone, with no sideways scroll', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/operator/tenants/new');
    await page.getByLabel('Tenant id').fill('example-phone');
    await page.getByLabel('Display name').fill('Example Phone');
    await page.getByLabel('Legal name').fill('Example Phone Organisation');
    await page.getByLabel('ODS code').fill('RZZ03');
    await page.getByRole('button', { name: 'Create tenant' }).click();
    await expect(page.getByRole('status')).toContainText('Tenant created.');
    await page.goto('/operator');
    await expect(page.getByRole('table', { name: 'Tenants' })).toBeVisible();
    // The header row is kept for assistive technology and drawn as nothing: each cell carries its own label.
    expect((await page.locator('thead').boundingBox())?.width ?? 0).toBeLessThanOrEqual(1);
    await expect(page.getByRole('cell').first()).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    expect(await axe(page)).toEqual([]);
  });
});

test.describe('the tenant administration frame', () => {
  test('has the logo, the organisation, the role in words, the navigation and a sign-out', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_A);
    await page.goto('/admin');
    await expect(page.getByRole('link', { name: 'Overwatch' })).toHaveAttribute('href', '/admin');
    await expect(page.getByText('Signed in as tenant administrator')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Administration' }).getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    expect(await axe(page)).toEqual([]);
  });
});

test.describe('the network administration frame', () => {
  test('has the logo, the role in words, the four pages and a sign-out, and passes axe', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    await page.goto('/network-admin/grants');
    await expect(page.getByRole('link', { name: 'Overwatch' })).toHaveAttribute('href', '/network-admin');
    await expect(page.getByText('Signed in as network administrator')).toBeVisible();
    const nav = page.getByRole('navigation', { name: 'Network administration' });
    await expect(nav.getByRole('link')).toHaveText(['Members', 'Grants', 'Listings', 'History']);
    await expect(nav.getByRole('link', { name: 'Grants' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    expect(await axe(page)).toEqual([]);
  });
});
