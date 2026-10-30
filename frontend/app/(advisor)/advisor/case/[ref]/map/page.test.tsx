import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { MAP_VIEW } from '@/test/fixtures/map';
import { BLANK_CASE, CASE_ETAG } from '@/test/msw/handlers/advisor';
import { byEl } from '@/test/el';
import { server } from '@/test/msw/server';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import MapPage from './page';

beforeEach(() => {
  push.mockReset();
  resetCsrfCache();
  server.use(
    http.get('/api/bff/cases/:ref', () =>
      HttpResponse.json({ ...BLANK_CASE, referrerType: 'gp', ageBand: '80+', postcode: 'DT4 8XX', needs: ['frailty'], urgency: 'within-2-hrs', etag: CASE_ETAG }),
    ),
    http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(MAP_VIEW)),
  );
});

describe('map page (W50)', () => {
  it('marks the Options step current, and shows the map with its heading near the postcode', async () => {
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }) }));

    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(await screen.findByRole('heading', { name: 'Options near DT4 8XX' })).toBeInTheDocument();
    expect(screen.getByText('Same services as the list. Sorted by travel time. Not ranked.')).toBeInTheDocument();
    expect(byEl('ADV-MAP-TOGGLE-MAP')).toHaveAttribute('aria-pressed', 'true');
  });

  it('the List toggle returns to the options list', async () => {
    const user = userEvent.setup();
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }) }));
    await screen.findByRole('heading', { name: 'Options near DT4 8XX' });

    await user.click(byEl('ADV-MAP-TOGGLE-LIST'));

    expect(push).toHaveBeenCalledWith('/advisor/case/4821/options');
  });

  it('a postcode that is not found shows the not-found state, not the map', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(notFound())));
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }) }));

    expect(await screen.findByRole('heading', { name: 'We could not find that postcode' })).toBeInTheDocument();
    expect(document.querySelector('[data-el="ADV-MAP-PIN-SVC-UCR-WEST"]')).toBeNull();
  });

  it('a postcode outside the area shows the outside-area state', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(outOfArea())));
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }) }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'No service covers this area' })).toBeInTheDocument());
  });
});

function notFound() {
  return { notFound: true, outOfArea: false, patientArea: null, options: [], notSuitable: [] };
}

function outOfArea() {
  return { notFound: false, outOfArea: true, patientArea: null, options: [], notSuitable: [] };
}
