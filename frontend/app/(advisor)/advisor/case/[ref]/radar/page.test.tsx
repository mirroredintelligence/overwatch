import { render, screen, within } from '@testing-library/react';
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
    ['radar', RadarPage, 'Who covers DT4 8XX', 'Radar'],
    ['compare', ComparePage, 'Compare for this patient', 'Compare'],
    ['ways', WaysPage, 'Meeting this need', 'Ways'],
  ] as const)('the %s page marks the Options step current and shows its screen for the case in the address', async (_name, Page, heading, tab) => {
    render(await Page({ params: Promise.resolve({ ref: '4821' }) }));

    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    const views = screen.getByRole('navigation', { name: 'Options view' });
    expect(within(views).getByRole('link', { name: tab })).toHaveAttribute('aria-current', 'page');
    expect(within(views).getByRole('link', { name: 'List' })).toHaveAttribute('href', '/advisor/case/4821/options');
    expect(screen.queryByRole('navigation', { name: 'Radar views' })).toBeNull();
  });
});
