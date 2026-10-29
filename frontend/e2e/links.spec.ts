import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { LINK } from '@/test/fixtures/links';
import { BACKEND_PORT } from './support/env';

// The capacity link page in a real browser (W04): what a reporter sees from a text, the one press
// that records a figure, and the rule that the page calls nothing but its own origin. The stand-in
// back end (e2e/support/backend.ts) answers the link routes from the same table as the unit tests.

const ORIGIN = 'http://localhost:3000';
const UNKNOWN = 'NoSuchLinkTokenAbcdefghij';

/** Every request the page makes that leaves its own origin, or reaches the back end port directly. */
function watchRequests(page: Page): string[] {
  const elsewhere: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin !== ORIGIN || url.port === String(BACKEND_PORT)) elsewhere.push(request.url());
  });
  return elsewhere;
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe('at phone width (390 CSS px)', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('shows the figure and its time, asks if it is still right, and calls nothing but its own origin', async ({ page }) => {
    const elsewhere = watchRequests(page);
    await page.goto(`/l/${LINK.recorded}`);

    await expect(page.getByRole('heading', { level: 1, name: 'UCR West' })).toBeVisible();
    await expect(page.getByText('We have 3 referrals in the next 2 hrs, as of 08:15. Still right?')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Yes, still 3' })).toBeVisible();
    await noHorizontalScroll(page);
    expect(elsewhere).toEqual([]);

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test('confirming a figure opens the thank-you page with the time it was recorded', async ({ page }) => {
    await page.goto(`/l/${LINK.recorded}`);
    await page.getByRole('button', { name: 'Yes, still 3' }).click();

    await expect(page).toHaveURL(new RegExp(`/l/${LINK.recorded}/thanks`));
    await expect(page.getByText('UCR West: 3 referrals in the next 2 hrs, recorded at 10:12.')).toBeVisible();
    await expect(page.getByText('You can close this page.')).toBeVisible();
    await noHorizontalScroll(page);
  });

  test('an expired link and an unknown one show the same page', async ({ page }) => {
    const expiredHeading = page.getByRole('heading', { level: 1, name: 'This link has expired' });
    await page.goto(`/l/${LINK.expired}`);
    await expect(expiredHeading).toBeVisible();
    const expired = await page.locator('main').innerText();
    await page.goto(`/l/${UNKNOWN}`);
    await expect(expiredHeading).toBeVisible();
    const unknown = await page.locator('main').innerText();

    expect(unknown).toBe(expired);
    await expect(page.getByRole('button', { name: 'Send me a new link' })).toBeVisible();
  });

  test('an expired link can ask for a new one', async ({ page }) => {
    await page.goto(`/l/${LINK.expired}`);
    await page.getByRole('button', { name: 'Send me a new link' }).click();

    await expect(page.getByText('We have sent a new link.')).toBeVisible();
  });

  test('a link with no figure yet asks for one, and its send button waits for a number', async ({ page }) => {
    await page.goto(`/l/${LINK.empty}`);

    await expect(page.getByText('How many referrals can you take in the next 2 hrs?')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Choose a number to send' })).toBeDisabled();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

test.describe('reflowed to 320 CSS px (the 200% zoom case)', () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test('the open link reflows without horizontal scrolling', async ({ page }) => {
    await page.goto(`/l/${LINK.recorded}`);
    await expect(page.getByRole('button', { name: 'Yes, still 3' })).toBeVisible();
    await noHorizontalScroll(page);
  });
});
