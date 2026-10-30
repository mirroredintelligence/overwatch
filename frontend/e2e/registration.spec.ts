import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

// Self-registration in a real browser (W23 to W27). The BFF's registration routes are answered by
// the test itself (page.route), so no back end and no session are needed: the browser's own code,
// the pages and the forms are what is under test. Sample values only. Written in the W23 to W27
// builds and NOT RUN in the build (the orchestrator runs e2e once at the end).

const ID = 'REG-SAMPLE-1';

async function answer(page: Page, path: RegExp, body: unknown, status = 200) {
  await page.route(path, (route: Route) =>
    route.fulfill({ status, contentType: 'application/json', headers: { 'Cache-Control': 'no-store' }, body: JSON.stringify(body) }),
  );
}

async function allowSession(page: Page) {
  await answer(page, /\/api\/bff\/session$/, { role: 'reporter', services: [], sub: 'person-sample-1', csrfToken: 'csrf-sample-token' });
}

test('sign-in sends the code request and never shows the whole number again', async ({ page }) => {
  await answer(page, /\/api\/bff\/identity\/code$/, { accepted: true, resendAfterSeconds: 60 }, 202);
  await page.goto(`/register?invite=InviteTokenSampleValue1`);
  await expect(page.getByRole('heading', { level: 1, name: 'Register your service' })).toBeVisible();
  await page.getByLabel('Mobile number').fill('07700 900456');
  await page.getByRole('button', { name: 'Send code' }).click();
  await expect(page.getByText('We sent a code to 07xxx xxx456.')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('07700 900456');
  await expect(page.locator('body')).not.toContainText('07700900456');
});

test('the sign-in and code pages have no axe violations', async ({ page }) => {
  await page.goto('/register?invite=InviteTokenSampleValue1');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('the start page leads to the organisation step', async ({ page }) => {
  await page.goto(`/register/${ID}/start`);
  await expect(page.getByRole('heading', { level: 1, name: 'Register a service' })).toBeVisible();
  await page.getByRole('link', { name: 'Start' }).click();
  await expect(page).toHaveURL(new RegExp(`/register/${ID}/organisation$`));
});

test('organisation: Continue with nothing shows the four problems, focused', async ({ page }) => {
  await allowSession(page);
  await answer(page, new RegExp(`/api/bff/registrations/${ID}$`), {
    id: ID,
    status: 'draft',
    invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
    steps: {},
  });
  await page.goto(`/register/${ID}/organisation`);
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'There are 4 problems' })).toBeVisible();
  await expect(page.getByRole('alert')).toBeFocused();
});

test('location: a visiting service goes straight to step 3', async ({ page }) => {
  await allowSession(page);
  await answer(page, new RegExp(`/api/bff/registrations/${ID}/steps/location$`), { status: 'draft' });
  await page.goto(`/register/${ID}/location`);
  await page.getByRole('button', { name: 'No, we visit patients' }).click();
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page).toHaveURL(new RegExp(`/register/${ID}/service$`));
});

test('review: a section that needs attention blocks submit', async ({ page }) => {
  await allowSession(page);
  await answer(page, new RegExp(`/api/bff/registrations/${ID}/review$`), {
    sections: [
      { key: 'organisation', status: 'complete', summary: 'Sample Community Trust' },
      { key: 'service', status: 'needs-attention', summary: 'UCR West · criteria review date missing' },
    ],
  });
  await page.goto(`/register/${ID}/review`);
  await page.getByRole('button', { name: 'Submit for approval' }).click();
  await expect(page.getByRole('link', { name: 'Service needs attention' })).toBeVisible();
});

test('status: needs changes lists the notes numbered, with the way to fix them', async ({ page }) => {
  await allowSession(page);
  await answer(page, new RegExp(`/api/bff/registrations/${ID}/status$`), {
    status: 'needs-changes',
    serviceName: 'UCR West',
    notes: ['The criteria owner email must be an organisation address.'],
    noteFrom: { role: 'SPOA shift lead', at: '2026-10-27T13:52:00Z' },
    details: { spoaPhone: '01305 123456' },
  });
  await page.goto(`/register/${ID}/status`);
  await expect(page.getByRole('heading', { level: 1, name: 'A few things to fix' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Fix and resubmit' })).toHaveAttribute('href', `/register/${ID}/review`);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test('my services lists the reporter’s services with their words', async ({ page }) => {
  await allowSession(page);
  await answer(page, /\/api\/bff\/registrations\/mine$/, {
    services: [{ id: ID, serviceName: 'UCR West', state: 'active', detail: 'Reporting every 2 hrs by text' }],
  });
  await page.goto('/register/services');
  await expect(page.getByRole('heading', { level: 1, name: 'My services' })).toBeVisible();
  await expect(page.getByText('Active')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Edit UCR West' })).toHaveAttribute('href', `/register/${ID}/status`);
});
