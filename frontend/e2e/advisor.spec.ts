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

// District chips (W50, W9H DEC-1045, DEC-1046). When the postcode was not found or no service covers its area,
// the options screen offers the districts the services cover; choosing one saves it on the case and runs the
// options again. The BFF routes are answered in the page, so the flow needs no seeded back end. Written, not run.
test.describe('district chips (W50)', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  });

  test('a postcode not found offers the districts, and choosing one shows the options again', async ({ page }) => {
    let chosen: unknown = null;
    let reads = 0;
    await page.route('**/api/bff/cases/case-1/options', async (route) => {
      reads += 1;
      const body =
        reads === 1
          ? { shownAt: '2026-10-30T14:12:00.000Z', options: [], notSuitable: [], patientArea: null, notFound: true, outOfArea: false, districts: ['DT1', 'DT3'] }
          : { shownAt: '2026-10-30T14:13:00.000Z', options: [], notSuitable: [], patientArea: null, notFound: false, outOfArea: false, districts: [] };
      await route.fulfill({ json: body });
    });
    await page.route('**/api/bff/cases/case-1/district', async (route) => {
      chosen = route.request().postDataJSON();
      await route.fulfill({ json: { id: 'case-1' } });
    });

    await page.goto('/advisor/case/case-1/options');
    await expect(page.getByRole('heading', { name: 'We could not find that postcode' })).toBeVisible();
    await expect(page.getByText('Options will use the district, with a wider travel range.')).toBeVisible();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

    await page.getByRole('button', { name: 'DT3' }).click();

    await expect(page.getByRole('heading', { name: 'No service fits right now' })).toBeVisible();
    expect(chosen).toEqual({ district: 'DT3' });
    expect(reads).toBe(2);
  });

  test('an area no service covers offers the districts too, and the other ways stay', async ({ page }) => {
    await page.route('**/api/bff/cases/case-1/options', async (route) => {
      await route.fulfill({ json: { shownAt: '2026-10-30T14:12:00.000Z', options: [], notSuitable: [], patientArea: null, notFound: false, outOfArea: true, districts: ['DT2'] } });
    });

    await page.goto('/advisor/case/case-1/options');
    await expect(page.getByRole('heading', { name: 'No service covers this area' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'DT2' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Other routes under local protocol' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Change the postcode' })).toBeVisible();
  });
});

// A recorded score is corrected with a reason, and a case someone else changed says so (B6, Q7, H-192).
// The BFF routes are answered in the page. Written, not run.
test.describe('score correction and a changed case (B6)', () => {
  const RECORDED = {
    id: 'case-1', reference: '4821', referrerType: 'ambulance-crew', ageBand: '80+', postcode: 'DT4', needs: ['frailty'],
    urgency: 'within-2-hrs', scores: [{ method: 'news2', value: 2 }], scoreCorrections: 0,
    openedAt: '2026-10-30T14:00:00Z', closed: false, closedAt: null, outcome: null, etag: 'W/"3"',
  };

  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  });

  test('a changed score needs a reason before it is saved, and is sent with it', async ({ page }) => {
    let put: { ifMatch: string | null; body: Record<string, unknown> } | null = null;
    await page.route('**/api/bff/cases/case-1', async (route) => {
      if (route.request().method() === 'PUT') {
        put = { ifMatch: route.request().headers()['if-match'] ?? null, body: route.request().postDataJSON() as Record<string, unknown> };
        await route.fulfill({ json: { ...RECORDED, scoreCorrections: 1, etag: 'W/"4"' } });
        return;
      }
      await route.fulfill({ json: RECORDED });
    });
    await page.route('**/api/bff/cases/case-1/options', (route) => route.fulfill({ json: { shownAt: '2026-10-30T14:12:00.000Z', options: [], notSuitable: [], patientArea: null, notFound: false, outOfArea: false, districts: [] } }));

    await page.goto('/advisor/case/case-1');
    await page.getByRole('button', { name: 'Correct a score' }).click();
    await page.locator('[data-el="ADV-SCORE-NEWS2-INPUT"]').fill('5');
    await expect(page.locator('[data-el="ADV-NEEDS-CONTINUE-BTN"]')).toBeDisabled();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

    await page.getByRole('radio', { name: 'I entered it wrongly' }).check();
    await page.locator('[data-el="ADV-NEEDS-CONTINUE-BTN"]').click();

    await expect(page).toHaveURL(/\/advisor\/case\/case-1\/options$/);
    expect(put).toEqual({ ifMatch: 'W/"3"', body: expect.objectContaining({ scores: [{ method: 'news2', value: 5 }], scoreCorrectionReason: 'typing-error' }) });
  });

  test('a case changed by someone else is not overwritten: it says so and reads the case again', async ({ page }) => {
    let reads = 0;
    await page.route('**/api/bff/cases/case-1', async (route) => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({ status: 412, json: { code: 'conflict' } });
        return;
      }
      reads += 1;
      await route.fulfill({ json: reads === 1 ? RECORDED : { ...RECORDED, urgency: 'today', etag: 'W/"4"' } });
    });

    await page.goto('/advisor/case/case-1');
    await page.locator('[data-el="ADV-NEEDS-CONTINUE-BTN"]').click();
    await expect(page.getByText('Someone changed this case since you opened it. Nothing of yours was saved.')).toBeVisible();

    await page.getByRole('button', { name: 'Read the case again' }).click();
    await expect(page.getByText(/Someone changed this case/)).toHaveCount(0);
    expect(reads).toBe(2);
  });
});
