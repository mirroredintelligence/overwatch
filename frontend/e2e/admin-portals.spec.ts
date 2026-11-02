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
    await expect(page.getByRole('banner').getByText('Platform operator')).toBeVisible();
    const nav = page.getByRole('navigation', { name: 'Platform console' });
    await expect(nav.getByRole('link', { name: 'Organisations' })).toHaveAttribute('aria-current', 'page');
    await expect(nav.getByRole('link', { name: 'Audit' })).toBeVisible();
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
    await expect(page.getByRole('banner').getByText('Support', { exact: true })).toBeVisible();
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
    await expect(done).toContainText('Their Microsoft account is waiting for you to confirm it.');
    await expect(done).toContainText('2 groups are mapped to roles.');

    await page.goto('/operator');
    const table = page.getByRole('table', { name: 'Tenants' });
    const row = table.getByRole('row', { name: /Example Trust E2E/ });
    await expect(row.getByText('Being set up')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Create a tenant' })).toBeVisible();
    expect(await axe(page)).toEqual([]);

    // The organisation's page is a guided "Go live": a task list of five parts and only the selected part beside it.
    // The sign-in is the part to do now, the identifiers are under closed technical details, and confirming it
    // completes the part and offers the next one.
    await row.getByRole('link', { name: 'Example Trust E2E' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Example Trust E2E' })).toBeVisible();
    const tasks = page.getByRole('navigation', { name: 'Go live tasks' });
    await expect(tasks.getByRole('listitem')).toHaveCount(5);
    await expect(tasks.getByRole('link', { name: /^Organisation and sign-in/ })).toHaveAttribute('aria-current', 'step');
    await expect(tasks.getByRole('listitem').first()).toContainText('In progress');
    await expect(page.getByRole('heading', { level: 2, name: 'Organisation and sign-in' })).toBeVisible();
    const signin = page.getByRole('region', { name: 'Connect their Microsoft work accounts' });
    await expect(signin.getByText(DIRECTORY)).toBeHidden();
    await signin.getByText('Technical details', { exact: true }).click();
    await expect(signin.getByText(DIRECTORY)).toBeVisible();
    await expect(signin.getByText('Waiting for you to confirm', { exact: true })).toBeVisible();
    await tasks.getByRole('link', { name: /Teams and people/ }).click();
    await expect(page.getByRole('heading', { level: 2, name: 'Teams and people' })).toBeFocused();
    const teams = page.getByRole('region', { name: 'Other teams' });
    await teams.getByText('Technical details', { exact: true }).click();
    await expect(teams.getByRole('table', { name: 'Teams in Microsoft' }).getByText('Shift leads')).toBeVisible();
    await expect(teams.getByRole('table', { name: 'Teams in Microsoft' }).getByText('Advisors')).toBeVisible();
    await tasks.getByRole('link', { name: /Go live/ }).click();
    await expect(page.getByRole('button', { name: 'Go live' })).toHaveCount(0);
    await expect(page.getByRole('list', { name: 'Still to do' }).getByRole('listitem').first()).toContainText('Organisation and sign-in');
    expect(await axe(page)).toEqual([]);
    await tasks.getByRole('link', { name: /Organisation and sign-in/ }).click();
    await signin.getByRole('button', { name: 'Confirm this is their Microsoft account' }).click();
    await expect(signin.getByText('Connected to Example Trust E2E’s Microsoft accounts.')).toBeVisible();
    await expect(signin.getByRole('button', { name: 'Confirm this is their Microsoft account' })).toHaveCount(0);
    await expect(tasks.getByRole('listitem').first()).toContainText('Completed');
    await page.getByRole('button', { name: 'Continue to Administrator approval' }).click();
    await expect(page.getByRole('heading', { level: 2, name: 'Administrator approval' })).toBeFocused();

    // Their administrator is named and emailed; the page shows only the masked address and that the link is
    // waiting (it is approved only once the back end sees the app installed).
    const consent = page.getByRole('region', { name: 'Ask their administrator to approve' });
    await expect(consent.getByText('No approval link has been sent yet.')).toBeVisible();
    await consent.getByLabel('Their administrator’s work email').fill('jane.admin@example-trust.test');
    await consent.getByRole('button', { name: 'Send the approval link to their administrator' }).click();
    await expect(consent.getByText('The approval link was emailed.')).toBeVisible();
    await expect(consent.getByText('Waiting for approval. The link went to j***@example-trust.test', { exact: false })).toBeVisible();
    await expect(consent.getByRole('button', { name: 'Send the link again' })).toBeVisible();
    await expect(tasks.getByRole('link', { name: /Administrator approval/ })).toContainText('Waiting for them');
    await expect(page.locator('body')).not.toContainText('jane.admin@example-trust.test');
    // The button under the pointer fades its colour for a moment (design system 5.2): let it settle before axe reads it.
    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    expect(await axe(page)).toEqual([]);
  });

  test('the organisation page passes axe at a phone width of 360, with no sideways scroll', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.goto('/operator/tenants/new');
    await page.getByLabel('Tenant id').fill('example-narrow');
    await page.getByLabel('Display name').fill('Example Narrow');
    await page.getByLabel('Legal name').fill('Example Narrow Organisation');
    await page.getByLabel('ODS code').fill('RZZ03');
    await page.getByRole('button', { name: 'Create tenant' }).click();
    await expect(page.getByRole('status')).toContainText('Tenant created.');
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto('/operator/tenants/example-narrow');
    await expect(page.getByRole('heading', { level: 1, name: 'Example Narrow' })).toBeVisible();
    await page.getByText('Technical details', { exact: true }).first().click();
    await expect(page.getByRole('navigation', { name: 'Go live tasks' })).toBeVisible();
    expect(await axe(page)).toEqual([]);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    // On a phone: one column, the task list first and the selected part under it.
    const list = (await page.getByRole('navigation', { name: 'Go live tasks' }).boundingBox())!;
    const part = (await page.getByRole('heading', { level: 2, name: 'Organisation and sign-in' }).boundingBox())!;
    expect(part.y).toBeGreaterThan(list.y + list.height);
    // On a desktop: two columns, the task list beside the part.
    await page.setViewportSize({ width: 1280, height: 900 });
    const wideList = (await page.getByRole('navigation', { name: 'Go live tasks' }).boundingBox())!;
    const widePart = (await page.getByRole('heading', { level: 2, name: 'Organisation and sign-in' }).boundingBox())!;
    expect(widePart.x).toBeGreaterThan(wideList.x + wideList.width);
    expect(await axe(page)).toEqual([]);
  });

  test('the text number part: send a test text, stop using a number, choose the shared line, and pass axe at 360 and 1280', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator', liveToken());
    await page.goto('/operator/tenants/new');
    await page.getByLabel('Tenant id').fill('example-texts');
    await page.getByLabel('Display name').fill('Example Texts');
    await page.getByLabel('Legal name').fill('Example Texts Organisation');
    await page.getByLabel('ODS code').fill('RZZ04');
    await page.getByRole('button', { name: 'Create tenant' }).click();
    await expect(page.getByRole('status')).toContainText('Tenant created.');
    await page.goto('/operator/tenants/example-texts');
    await page.getByRole('navigation', { name: 'Go live tasks' }).getByRole('link', { name: /Reach and agreements/ }).click();
    const reach = page.getByRole('region', { name: 'Web address and text number' });

    // Record the organisation's own number, then send a real test text from it: the page says the provider accepted it.
    await reach.getByRole('textbox', { name: 'Text number', exact: true }).fill('+441632960011');
    await reach.getByLabel('Text account').fill('ACe2e');
    await reach.getByLabel('Sender name').fill('ExampleTexts');
    await reach.getByRole('button', { name: 'Record text number' }).click();
    const line = reach.getByRole('list', { name: 'Text numbers' }).getByRole('listitem');
    await expect(line).toContainText('+441632960011 · In use · Not tested');
    await expect(reach.getByRole('button', { name: /Mark .* as tested/ })).toHaveCount(0);
    const form = reach.getByRole('form', { name: 'Send a test text from +441632960011' });
    await form.getByLabel('Mobile phone to send the test to').fill('07700 900456');
    await form.getByRole('button', { name: 'Send a test text' }).click();
    await expect(form.getByRole('status')).toContainText('the text provider accepted the text');
    await expect(line).toContainText('Tested');
    await expect(page.locator('body')).not.toContainText('07700 900456');

    // The shared line is for sending only, and it says so.
    await expect(reach.getByText('People cannot reply by text until the organisation has its own number.', { exact: false })).toBeVisible();
    await reach.getByRole('button', { name: 'Use Overwatch’s shared line (sending only)' }).click();
    await expect(reach.getByRole('form', { name: 'Send a test text from the shared line' })).toBeVisible();

    // Stopping a number asks first, then says it is stopped and held.
    await reach.getByRole('button', { name: 'Stop using +441632960011' }).click();
    await expect(reach.getByRole('group', { name: 'Stop using +441632960011' })).toContainText('no other organisation can take it');
    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    expect(await axe(page)).toEqual([]);
    await reach.getByRole('button', { name: 'Yes, stop using it' }).click();
    await expect(line).toContainText('Stopped');
    await expect(reach.getByText('held for this organisation', { exact: false })).toBeVisible();

    for (const width of [360, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.mouse.move(0, 0);
      await page.waitForTimeout(400);
      expect(await axe(page)).toEqual([]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    }
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
    await expect(page.getByRole('banner').getByText('Tenant administrator')).toBeVisible();
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
    await expect(page.getByRole('banner').getByText('Network administrator')).toBeVisible();
    const nav = page.getByRole('navigation', { name: 'Network administration' });
    await expect(nav.getByRole('link')).toHaveText(['Members', 'Grants', 'Listings', 'History']);
    await expect(nav.getByRole('link', { name: 'Grants' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    expect(await axe(page)).toEqual([]);
  });
});
