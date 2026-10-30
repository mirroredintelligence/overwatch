import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// The advisor screens in a real browser (W10 to W16, W50). WRITTEN, NOT RUN: the orchestrator runs the
// e2e suite once at the end of the wave (docs/delivery/build-wave-rules.md). The call flow below needs
// back-end reads that R07 does not provide yet (GET ServiceRequest, the case reference, and the
// $filter-options parts for positions and travel), so it is marked fixme with the reason, not shown to pass.

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

test.describe('call flow (W11 to W16, W50)', () => {
  test.fixme(
    'start a call, record the needs, read the options, record the outcome and copy the summary',
    async ({ page }) => {
      // Blocked on the back end, not on this screen: no GET /fhir/ServiceRequest/{id}; POST refuses an
      // open without a referrer-type; PUT ignores age band and referrer; $filter-options has no
      // category, phone, positions, travel legs or flags. See docs/delivery/fragments/W10.md to W50.md.
      void page;
    },
  );
});
