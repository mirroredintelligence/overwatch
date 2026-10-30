import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// The advisor screens in a real browser (W10 to W16, W20, W21, W50). WRITTEN, NOT RUN: the orchestrator
// runs the e2e suite once at the end of the wave (docs/delivery/build-wave-rules.md). The stand-in back
// end answers the call-flow routes with the JSON the real back end's mapping writes (e2e/support/advisor.ts).

test.describe('advisor home and board (W10)', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  });

  test('the home shows "Ready for calls", the board counts and no axe violations', async ({ page }) => {
    await page.goto('/advisor');

    await expect(page.getByRole('heading', { name: 'Ready for calls' })).toBeVisible();
    await expect(page.locator('[data-el="ADV-HOME-COUNT-ACCEPTING"]')).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test('the wall board view opens for the advisor session', async ({ page }) => {
    await page.goto('/advisor/board');

    await expect(page.getByRole('heading', { name: 'Dorset urgent care capacity' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Back to advisor home' })).toBeVisible();
  });
});

test.describe('call flow (W10 to W16, W20, W21, W50)', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  });

  test('start a call, record the needs, read the options, ask for a booking, and record the outcome', async ({ page }) => {
    await page.goto('/advisor');
    await page.getByRole('button', { name: 'Start a new call' }).click();
    // The address names the case by its id, not by the four-digit number (DEC-631).
    await expect(page).toHaveURL(/\/advisor\/case\/case-1$/);

    await page.locator('[data-el="ADV-NEEDS-REFERRER-AMBULANCE"]').click();
    await page.locator('[data-el="ADV-NEEDS-AGE-80PLUS"]').click();
    await page.getByLabel('Where is the patient? Postcode').fill('DT4 8XX');
    await page.locator('[data-el="ADV-NEEDS-NEED-FRAILTY"]').click();
    await page.locator('[data-el="ADV-NEEDS-URGENCY-WITHIN-2-HRS"]').click();
    await page.locator('[data-el="ADV-NEEDS-CONTINUE-BTN"]').click();

    await expect(page).toHaveURL(/\/advisor\/case\/case-1\/options$/);
    await expect(page.getByRole('heading', { name: '2 services meet this patient\'s criteria' })).toBeVisible();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

    const ucr = page.getByRole('article', { name: 'UCR West' });
    await ucr.getByRole('button', { name: 'Criteria' }).click();
    await expect(page.getByText('Fall, no injury · Frailty · Age 18+')).toBeVisible();
    await page.keyboard.press('Escape');

    await ucr.getByRole('button', { name: 'Request booking' }).click();
    await expect(ucr.getByText('Requested')).toBeVisible();

    await page.goto('/advisor/case/case-1/finish');
    await page.locator('[data-el="ADV-FIN-OUTCOME-DECLINED"]').click();
    await page.locator('[data-el="ADV-FIN-SAVE-BTN"]').click();
    await expect(page.getByRole('heading', { name: 'Call closed' })).toBeVisible();
    await expect(page.getByText('Case 4821 is saved. The postcode has been cleared from this screen.')).toBeVisible();
  });
});
