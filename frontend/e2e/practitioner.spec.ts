import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, test } from '@playwright/test';
import { BACKEND_PORT, SITE_URL } from './support/env';
import { signIn } from './support/session';
import { TOKEN_ORG_A } from './support/tokens';

// The practitioner app in a real browser, at phone width (RadarPhone 1 to 4), against the stand-in back end's
// practitioner routes (e2e/support/practitioner.ts). The stand-in keeps the state of each offer, so the tests
// share one worker's state in order (serial) and start by resetting it. Nothing here is a real address,
// name or number.

const PHONE = { width: 360, height: 800 };
const WIDER_PHONE = { width: 390, height: 844 };
// A page's first visit compiles it in the dev server, while another worker may do the same: give it time.
const FIRST = { timeout: 30_000 };
const ELEMENT_ID = /^[A-Z0-9]+(-[A-Z0-9]+)*$/;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const reset = await fetch(`http://127.0.0.1:${BACKEND_PORT}/practitioner/__reset`, { method: 'POST' });
  expect(reset.status).toBe(200);
});

test.beforeEach(async ({ page }) => {
  await page.setViewportSize(PHONE);
  await signIn(page.context(), SITE_URL, 'reporter', TOKEN_ORG_A);
});

async function noSidewaysScroll(page: Page) {
  const { scroll, client } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(scroll).toBeLessThanOrEqual(client);
}

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}

async function elementIdsAreUppercase(page: Page) {
  const ids = await page.locator('[data-el]').evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-el') ?? ''));
  expect(ids.length).toBeGreaterThan(0);
  for (const id of ids) expect(id).toMatch(ELEMENT_ID);
}

test('with no session the shift goes to the PIN screen', async ({ page, context }) => {
  await context.clearCookies();
  await page.goto('/app/practitioner');
  await expect(page).toHaveURL(/\/app\/pin$/, FIRST);
});

test('my shift: greeting, optional status, today, the offers waiting, and the note about location', async ({ page }) => {
  await page.goto('/app/practitioner');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/^Good (morning|afternoon|evening)$/, FIRST);
  await expect(page.getByText('Optional')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Available' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText(/^Today: \d+ visits?$/)).toBeVisible();
  await expect(page.getByText('Your location is not shared unless you turn it on for a visit.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'See today’s round' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Share location during visits' })).toBeVisible();
  await expect(page.getByRole('link', { name: /Fall, no injury/ }).first()).toContainText('Sector DT4 8');
  // The shift names a sector and a need, and never an address or a contact.
  await expect(page.locator('body')).not.toContainText('Synthetic');
  await expect(page.locator('body')).not.toContainText('07000');
  await noSidewaysScroll(page);
  await elementIdsAreUppercase(page);
  await axe(page);
  await page.setViewportSize(WIDER_PHONE);
  await noSidewaysScroll(page);
});

test('the status is optional: one press sets it and another clears it', async ({ page }) => {
  await page.goto('/app/practitioner');
  const breakChip = page.getByRole('button', { name: 'Break' });
  await breakChip.click({ ...FIRST });
  await expect(breakChip).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Available' })).toHaveAttribute('aria-pressed', 'false');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Break' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Break' }).click();
  await expect(page.getByRole('button', { name: 'Break' })).toHaveAttribute('aria-pressed', 'false');
  await page.reload();
  for (const word of ['Available', 'On a visit', 'Break', 'Off shift']) await expect(page.getByRole('button', { name: word })).toHaveAttribute('aria-pressed', 'false');
});

test('a visit offer: the need, the sector, when it is wanted, the countdown, and the address only after accepting', async ({ page }) => {
  await page.goto('/app/practitioner/offers/pr-axe');
  await expect(page.getByText('New offer')).toBeVisible(FIRST);
  await expect(page.getByRole('heading', { level: 1, name: 'Fall, no injury' })).toBeVisible();
  await expect(page.getByText('Area DT4 8 (sector)')).toBeVisible();
  await expect(page.getByText('Wanted within 2 hrs')).toBeVisible();
  await expect(page.getByText(/Offer expires in \d:\d\d/)).toBeVisible();
  await expect(page.getByText('The address and contact appear only after you accept.')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Synthetic');
  await expect(page.getByRole('button', { name: 'Accept visit' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Decline' })).toBeVisible();
  await noSidewaysScroll(page);
  await elementIdsAreUppercase(page);
  await axe(page);
});

test('accepting shows the address and contact, then the status list takes the visit to done and the details go', async ({ page }) => {
  await page.goto('/app/practitioner/offers/pr-accept');
  await page.getByRole('button', { name: 'Accept visit' }).click(FIRST);
  await expect(page).toHaveURL(/\/app\/practitioner\/visits\/pr-accept$/);
  await expect(page.getByText('Accepted', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { level: 1, name: 'Visit 4821' })).toBeVisible();
  await expect(page.getByText('Address and contact now shown to you only.')).toBeVisible();
  await expect(page.getByText('1 Synthetic Street')).toBeVisible();
  await expect(page.getByText('Daughter, 07000 000000')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open in maps' })).toHaveAttribute('href', /^geo:0,0\?q=/);
  await expect(page.getByRole('button', { name: 'Update status' })).toBeDisabled();
  await noSidewaysScroll(page);
  await elementIdsAreUppercase(page);
  await axe(page);

  await page.getByRole('button', { name: 'Arrived' }).click();
  await page.getByRole('button', { name: 'Update status' }).click();
  await expect(page.getByText('Status updated: Arrived.')).toBeVisible();
  await page.getByRole('button', { name: 'Visit done' }).click();
  await page.getByRole('button', { name: 'Update status' }).click();
  await expect(page.getByRole('heading', { name: 'Visit done' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Synthetic');
  await expect(page.locator('body')).not.toContainText('07000');
  await axe(page);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Visit done' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Synthetic');
});

test('could not reach the patient closes the visit and removes the details', async ({ page }) => {
  await page.goto('/app/practitioner/offers/pr-notreached');
  await page.getByRole('button', { name: 'Accept visit' }).click(FIRST);
  await expect(page.getByText('1 Synthetic Street')).toBeVisible();
  await page.getByRole('button', { name: 'Could not reach the patient' }).click();
  await page.getByRole('button', { name: 'Update status' }).click();
  await expect(page.getByRole('heading', { name: 'Could not reach the patient' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Synthetic');
});

test('declining goes back to the shift and the offer is gone from it', async ({ page }) => {
  await page.goto('/app/practitioner/offers/pr-decline');
  await page.getByRole('button', { name: 'Decline' }).click(FIRST);
  await expect(page).toHaveURL(/\/app\/practitioner$/);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await page.goto('/app/practitioner/visits/pr-decline');
  await expect(page.getByRole('heading', { name: 'Offer declined' })).toBeVisible();
});

test('when a colleague took the visit first the person is told, with nothing of it shown', async ({ page }) => {
  await page.goto('/app/practitioner/offers/pr-taken');
  await page.getByRole('button', { name: 'Accept visit' }).click(FIRST);
  await expect(page.getByRole('heading', { name: 'No longer open' })).toBeVisible();
  await expect(page.getByText('This visit was taken by a colleague, or the booking was cancelled.')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('Synthetic');
  await axe(page);
});

test('an offer that runs out of time says so', async ({ page }) => {
  await page.goto('/app/practitioner/offers/pr-expiring');
  await expect(page.getByRole('heading', { name: 'Offer expired' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('button', { name: 'Accept visit' })).toHaveCount(0);
});

test('an offer that is not the person’s is not shown', async ({ page }) => {
  await page.goto('/app/practitioner/offers/someone-elses');
  await expect(page.getByText('We could not load this visit. Try again shortly.')).toBeVisible(FIRST);
  await expect(page.locator('body')).not.toContainText('Synthetic');
});

test('location sharing: two answers, three reassurances, and the choice is saved', async ({ page }) => {
  await page.goto('/app/practitioner/location');
  await expect(page.getByRole('heading', { level: 1, name: 'Share your location on visits?' })).toBeVisible(FIRST);
  await expect(page.getByRole('button', { name: 'Never' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('The coordinator sees your estimated arrival, not a trail.')).toBeVisible();
  await expect(page.getByText('It stops when you arrive.')).toBeVisible();
  await expect(page.getByText('It is not used to time or rank you.')).toBeVisible();
  await expect(page.getByText('You can change this at any time in Settings.')).toBeVisible();
  await noSidewaysScroll(page);
  await elementIdsAreUppercase(page);
  await axe(page);

  await page.getByRole('button', { name: 'Only while I travel to a visit' }).click();
  await page.getByRole('button', { name: 'Save choice' }).click();
  await expect(page.getByText('Your choice is saved.')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Only while I travel to a visit' })).toHaveAttribute('aria-pressed', 'true');
});

test('with sharing on, on my way offers an estimate in minutes, and the phone’s position is never asked for', async ({ page, context }) => {
  // A page that asked for the position would be refused: the browser has no permission to give.
  await context.grantPermissions([], { origin: SITE_URL });
  await page.addInitScript(() => {
    (window as unknown as { __geolocationAsked: number }).__geolocationAsked = 0;
    const asked = () => {
      (window as unknown as { __geolocationAsked: number }).__geolocationAsked += 1;
    };
    Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: asked, watchPosition: asked, clearWatch: asked }, configurable: true });
  });
  await page.goto('/app/practitioner/location');
  await page.getByRole('button', { name: 'Only while I travel to a visit' }).click(FIRST);
  await page.getByRole('button', { name: 'Save choice' }).click();
  await expect(page.getByText('Your choice is saved.')).toBeVisible();
  await page.goto('/app/practitioner/visits/pr-status');
  await page.getByRole('button', { name: 'Accept visit' }).click(FIRST);
  await expect(page.getByRole('heading', { level: 1, name: 'Visit 4821' })).toBeVisible();
  await page.getByRole('button', { name: 'On my way' }).click();
  const group = page.getByRole('group', { name: 'Estimated arrival' });
  await expect(group.getByText('You choose the estimate. Your phone’s position is not sent.')).toBeVisible();
  await group.getByRole('button', { name: '20 min' }).click();
  await page.getByRole('button', { name: 'Update status' }).click();
  await expect(page.getByText('Status updated: On my way.')).toBeVisible();
  await expect(page.getByText(/^Estimated arrival shared: \d\d:\d\d\.$/)).toBeVisible();
  await axe(page);
  await page.getByRole('button', { name: 'Arrived' }).click();
  await page.getByRole('button', { name: 'Update status' }).click();
  await expect(page.getByText('Status updated: Arrived.')).toBeVisible();
  await expect(page.getByText(/Estimated arrival shared/)).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __geolocationAsked: number }).__geolocationAsked)).toBe(0);
});

test('today’s round lists the visits by sector, with no address', async ({ page }) => {
  await page.goto('/app/practitioner/round');
  await expect(page.getByRole('heading', { level: 1, name: 'Today’s round' })).toBeVisible(FIRST);
  const rows = page.getByRole('list', { name: 'Today’s visits' }).getByRole('link');
  await expect(rows.first()).toContainText('sector DT4 8');
  await expect(page.locator('body')).not.toContainText('Synthetic');
  await noSidewaysScroll(page);
  await elementIdsAreUppercase(page);
  await axe(page);
});

test('the BFF answers a person with no practitioner session with a 401 and no data', async ({ request }) => {
  const response = await request.get(`${SITE_URL}/api/bff/practitioner/shift`);
  expect(response.status()).toBe(401);
  expect(await response.text()).not.toContain('Synthetic');
});
