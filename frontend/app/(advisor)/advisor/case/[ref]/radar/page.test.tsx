import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { RADAR_VIEW } from '@/test/fixtures/radar';
import { BLANK_CASE, CASE_ETAG } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import ComparePage from '../compare/page';
import WaysPage from '../ways/page';
import RadarPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  resetCsrfCache();
  server.use(
    http.get('/api/bff/cases/:ref', () => HttpResponse.json({ ...BLANK_CASE, referrerType: 'gp', ageBand: '80+', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'within-2-hrs', etag: CASE_ETAG })),
    http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(RADAR_VIEW)),
  );
});

describe('the radar pages (RadarWeb 1, 2, 6)', () => {
  it.each([
    ['radar', RadarPage, 'Who covers DT4 8XX'],
    ['compare', ComparePage, 'Compare for this patient'],
    ['ways', WaysPage, 'Meeting this need'],
  ] as const)('the %s page marks the Options step current and shows its screen for the case in the address', async (_name, Page, heading) => {
    render(await Page({ params: Promise.resolve({ ref: '4821' }) }));

    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Radar views' })).toBeInTheDocument();
  });
});
