import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { SITE_URL } from './support/env';
import { signIn } from './support/session';
import { TOKEN_ORG_A, TOKEN_ORG_B } from './support/tokens';

// The network administration (TEN-080) and the sharing screen (TEN-081) as a browser sees them. Written in the
// build wave and not run there: the verification run executes it (pnpm e2e). The browser stand-in
// (e2e/support/networkAdmin.ts) serves one network, of which organisation A's token is the owner and
// organisation B's is a member; any other token is in none.

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa'];
const OWNER_PAGES = ['/network-admin', '/network-admin/grants', '/network-admin/listings', '/network-admin/history'];

test.describe('the network administration', () => {
  test('is the network administrator’s alone: every other role is shown the forbidden page', async ({ page }) => {
    for (const role of ['tenant-admin', 'lead', 'advisor', 'exec']) {
      await page.context().clearCookies();
      await signIn(page.context(), SITE_URL, role, TOKEN_ORG_A);
      for (const path of OWNER_PAGES) {
        await page.goto(path);
        await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible();
      }
    }
  });

  test('sends a request with no session to sign-in, with the page to come back to', async ({ page }) => {
    await page.goto('/network-admin/grants');
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fnetwork-admin%2Fgrants$/);
  });

  test('the owner reads the members, in words, with the sentence about what it does not see, and the page passes axe', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    await page.goto('/network-admin');
    await expect(page.getByRole('heading', { level: 1, name: 'Network members' })).toBeVisible();
    await expect(page.getByText("You never see another organisation's private data.")).toBeVisible();
    const table = page.locator('[data-el="NADM-MEMBERS-TABLE"]');
    await expect(table.getByRole('row')).toHaveCount(7);
    await expect(table.getByText('Agreement version 2 is available')).toBeVisible();
    expect((await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()).violations).toEqual([]);
  });

  test('the address of an administration page names no network, tenant or scope', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    for (const path of OWNER_PAGES) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      expect(page.url()).not.toMatch(/net-|tenant|scope|network[A-Za-z]*=/i);
    }
  });

  test('inviting by organisation code says one thing for a code that does not work', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    await page.goto('/network-admin');
    await page.locator('[data-el="NADM-MEMBER-ADD-BTN"]').click();
    await page.getByLabel('Organisation code').fill('nobody-here');
    await page.locator('[data-el="NADM-MEMBER-SEND-BTN"]').click();
    await expect(page.getByText('We could not add that organisation. Check the code with them.')).toBeVisible();
    await page.getByLabel('Organisation code').fill('sample-area-c');
    await page.locator('[data-el="NADM-MEMBER-SEND-BTN"]').click();
    await expect(page.getByRole('status')).toContainText('Invitation sent.');
  });

  test('ending a membership asks first and keeps focus where it was', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    await page.goto('/network-admin');
    const opener = page.getByRole('button', { name: /^End membership of Sample Area A$/ });
    await opener.click();
    await expect(page.getByRole('dialog', { name: 'End membership for Sample Area A?' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test('the owner approves a grant that waits for it and cannot end a member’s grant', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    await page.goto('/network-admin/grants');
    await expect(page.locator('[data-el="NADM-GRANTS-TABLE"]')).toBeVisible();
    await page.getByRole('button', { name: 'Approve Capacity grant of Sample Area A' }).click();
    await expect(page.getByRole('status')).toContainText('Your approval is recorded.');
    await expect(page.getByRole('button', { name: /^End/ })).toHaveCount(0);
    expect((await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()).violations).toEqual([]);
  });

  test('a listing is paused with a reason from the fixed list, never words', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    await page.goto('/network-admin/listings');
    await page.getByRole('button', { name: 'Pause svc-sdec of Sample Area A' }).click();
    await page.getByRole('combobox', { name: 'Reason' }).selectOption({ label: 'Data quality' });
    await page.locator('[data-el="NADM-LISTING-CONFIRM-BTN"]').click();
    await expect(page.getByRole('status')).toContainText('Listing paused.');
  });

  test('an owner of no network reads "Network view not available" and nothing else', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_B);
    await page.goto('/network-admin');
    await expect(page.getByText('Network view not available')).toBeVisible();
    await expect(page.locator('[data-el="NADM-MEMBERS-TABLE"]')).toHaveCount(0);
  });

  test('the BFF routes refuse a request that names a network, a tenant or a scope', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'network-admin', TOKEN_ORG_A);
    for (const query of ['tenant=x', 'scope=y', 'network=net-sample', 'networkIds=net-sample']) {
      expect((await page.request.get(`/api/bff/network-admin?${query}`)).status(), query).toBe(400);
    }
    expect((await page.request.get('/api/bff/network-admin?networkId=net-other')).status()).toBe(404);
  });
});

test.describe('sharing with the network', () => {
  test('is the tenant administrator’s alone', async ({ page }) => {
    for (const role of ['network-admin', 'lead', 'advisor']) {
      await page.context().clearCookies();
      await signIn(page.context(), SITE_URL, role, TOKEN_ORG_B);
      await page.goto('/admin/sharing');
      await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible();
    }
  });

  test('shows a card for each kind with its state and exactly which fields leave, and passes axe', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_B);
    await page.goto('/admin/sharing');
    await expect(page.getByRole('heading', { level: 1, name: 'Sharing with the network' })).toBeVisible();
    await expect(page.locator('[data-el="SHARE-SCOPE-CARD"]')).toHaveCount(3);
    await expect(page.locator('[data-el="SHARE-FIELDS-LIST"]')).toHaveCount(3);
    await expect(page.getByText('Never shared: reporters')).toBeVisible();
    await expect(page.getByText('Postcode district only (for example DT4)')).toBeVisible();
    expect((await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()).violations).toEqual([]);
  });

  test('gives the organisation its own code and no other identifier', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_B);
    await page.goto('/admin/sharing');
    const code = page.getByRole('region', { name: 'Your organisation code' });
    await expect(code).toBeVisible();
    expect(page.url()).not.toMatch(/net-|tenant|scope|network[A-Za-z]*=/i);
  });

  test('ending sharing asks first, in the design’s words, and keeps focus where it was', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_B);
    await page.goto('/admin/sharing');
    const opener = page.getByRole('button', { name: /^End sharing/ }).first();
    await opener.click();
    await expect(page.getByRole('dialog', { name: /^End sharing/ })).toContainText('New data stops being shared straight away.');
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
  });

  test('a read the back end refuses says it could not load, and offers nothing to do', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_A);
    await page.goto('/admin/sharing');
    await expect(page.getByText('We could not load what your organisation shares.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Propose sharing|Approve/ })).toHaveCount(0);
  });
});
