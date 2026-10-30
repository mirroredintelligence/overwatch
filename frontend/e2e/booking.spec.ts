import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { BOOKING_CHANGE_TOKEN, LINK } from '@/test/fixtures/links';
import { BACKEND_PORT, SITE_URL } from './support/env';

// The service's booking request page in a real browser (W19): the request as the service reads it,
// a confirm, and a decline with a reason. Written, not run: the orchestrator runs e2e at the end of
// the wave. The stand-in back end answers from the same table as the unit tests (test/fixtures/links.ts).

const ORIGIN = SITE_URL;

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

test.describe('booking request at phone width (390 CSS px)', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('shows the request, posts nothing on opening, and is clean for axe', async ({ page }) => {
    const elsewhere = watchRequests(page);
    await page.goto(`/l/${LINK.booking}/booking`);
    await expect(page.getByRole('heading', { level: 1, name: 'UCR West' })).toBeVisible();
    await expect(page.getByText('Not booked until you confirm. Reply by 14:26.')).toBeVisible();
    await noHorizontalScroll(page);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
    expect(elsewhere).toEqual([]);
  });

  test('confirms the booking and offers the change link', async ({ page }) => {
    await page.goto(`/l/${LINK.booking}/booking`);
    await page.getByRole('button', { name: 'Confirm booking' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Booked' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Tell us something changed' })).toHaveAttribute(
      'href',
      `/l/${BOOKING_CHANGE_TOKEN}/booking/change`,
    );
  });

  test('declines with a reason', async ({ page }) => {
    await page.goto(`/l/${LINK.booking}/booking`);
    await page.getByRole('button', { name: 'Outside our criteria' }).click();
    await page.getByRole('button', { name: 'Decline' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Declined' })).toBeVisible();
  });
});
