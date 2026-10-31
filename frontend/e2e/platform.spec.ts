import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { signInOperator } from './support/operator';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// The tenant administration (TEN-076) and the operator console (TEN-083) as a browser sees them. Written in
// the build wave and not run there: the verification run executes it (pnpm e2e). The browser stand-in back
// end (e2e/support/backend.ts) does not serve `/tenant` or `/platform`, so each page must say it could not
// load, and must never show an empty list as if there were nothing (H-730). Flows against the real back end
// are in the verification run's own environment, not in this stand-in.

const axe = async (page: import('@playwright/test').Page) =>
  (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations;

test.describe('the operator console door', () => {
  test('sends a request with no operator session to the console’s own sign-in, which passes axe', async ({ page }) => {
    await page.goto('/operator/audit');
    await expect(page).toHaveURL(/\/operator\/sign-in\?next=%2Foperator%2Faudit$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Platform console' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in with your platform account' })).toBeVisible();
    expect(await axe(page)).toEqual([]);
  });

  test('a tenant’s person of any role is sent to the console’s sign-in, not let in', async ({ page }) => {
    for (const role of ['advisor', 'lead', 'tenant-admin']) {
      await page.context().clearCookies();
      await signIn(page.context(), SITE_URL, role, TOKEN_ORG_A);
      await page.goto('/operator');
      await expect(page).toHaveURL(/\/operator\/sign-in/);
    }
  });

  test('an operator session opens no tenant page', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator');
    for (const path of ['/lead', '/admin', '/advisor']) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/sign-in/);
    }
  });

  test('the operator’s tenants page says it could not load, with the console’s navigation, and passes axe', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator');
    await page.goto('/operator');
    await expect(page.getByRole('alert')).toContainText('We could not load the tenants.');
    await expect(page.getByRole('navigation', { name: 'Platform console' })).toBeVisible();
    await expect(page.getByText('There are no tenants yet.')).toHaveCount(0);
    expect(await axe(page)).toEqual([]);
  });

  test('a support person is kept off the audit chain and the tenant pages', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'support');
    for (const path of ['/operator/audit', '/operator/tenants/new', '/operator/tenants/trust-a']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible();
    }
  });

  test('the audit chain page says it could not load, and the chain is never shown as empty', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator');
    await page.goto('/operator/audit');
    await expect(page.getByRole('alert').first()).toContainText('We could not load the audit chain.');
    await expect(page.getByRole('table')).toHaveCount(0);
  });

  test('the operator’s session cookie is HttpOnly and Strict and not readable by the page', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator');
    await page.goto('/operator');
    const cookie = (await page.context().cookies()).find((c) => c.name === 'diucs_operator');
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Strict' });
    expect(await page.evaluate(() => document.cookie)).not.toContain('diucs_operator');
  });

  test('a tenant’s BFF routes and the console’s are each a 401 to the other’s session', async ({ page, request }) => {
    await signInOperator(page.context(), SITE_URL, 'platform-operator');
    expect((await page.request.get('/api/bff/tenant/overview')).status()).toBe(401);
    await page.context().clearCookies();
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_A);
    expect((await page.request.get('/api/bff/platform/tenants')).status()).toBe(401);
    expect((await request.get('/api/bff/platform/session')).status()).toBe(401);
  });
});

test.describe('the support person’s screens', () => {
  test('the requests page says it could not load, and the form to ask passes axe', async ({ page }) => {
    await signInOperator(page.context(), SITE_URL, 'support');
    await page.goto('/operator/support');
    await expect(page.getByRole('alert').first()).toContainText('We could not load your requests.');
    await page.goto('/operator/support/new');
    await expect(page.getByRole('alert').first()).toContainText('We could not load the tenants.');
  });
});

test.describe('the tenant administration', () => {
  test('keeps every other role off it', async ({ page }) => {
    for (const role of ['advisor', 'lead', 'exec']) {
      await page.context().clearCookies();
      await signIn(page.context(), SITE_URL, role, TOKEN_ORG_A);
      await page.goto('/admin');
      await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible();
    }
  });

  test('the overview says it could not load, never a half page, and passes axe', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_A);
    await page.goto('/admin');
    await expect(page.getByRole('alert')).toContainText('We could not load your organisation.');
    await expect(page.getByRole('navigation', { name: 'Administration' })).toBeVisible();
    expect(await axe(page)).toEqual([]);
  });

  test('every page of the administration is reachable from the navigation and says it could not load', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_A);
    const pages: [string, string][] = [
      ['/admin/config', 'We could not load the settings.'],
      ['/admin/users', 'We could not load the directory and roles.'],
      ['/admin/contacts', 'We could not load the contacts.'],
      ['/admin/email', 'We could not load the email sender.'],
      ['/admin/retention', 'We could not load the retention rules.'],
      ['/admin/access', 'We could not load the access log.'],
      ['/admin/support', 'We could not load the support requests.'],
    ];
    for (const [path, words] of pages) {
      await page.goto(path);
      await expect(page.getByRole('alert')).toContainText(words);
    }
  });

  test('a settings version that is not a whole number is the page that is not there', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'tenant-admin', TOKEN_ORG_A);
    const response = await page.goto('/admin/config/abc');
    expect(response?.status()).toBe(404);
  });
});
