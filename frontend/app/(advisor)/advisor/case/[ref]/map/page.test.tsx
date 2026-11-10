import { render, screen, waitFor, within } from '@testing-library/react';
import { networkBffHandlers } from '@/test/msw/handlers/networkBff';
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

describe('map page: the scope header (WB11)', () => {
  it('says it shows our organisation’s options and offers the network’s map, when the organisation is in a network', async () => {
    server.use(...networkBffHandlers);
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));
    const header = screen.getByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Our organisation');
    const nav = await within(header).findByRole('navigation', { name: 'Choose the board' });
    expect(within(nav).getByRole('link', { name: 'Network' })).toHaveAttribute('href', '/advisor/case/4821/network-map');
    expect(within(nav).getByRole('link', { name: 'Our organisation' })).toHaveAttribute('href', '/advisor/case/4821/map');
  });
});

describe('map page (W50)', () => {
  it('marks the Options step current, and shows the map with its heading near the postcode', async () => {
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));

    expect(document.querySelector('[data-step="options"]')).toHaveAttribute('aria-current', 'step');
    expect(await screen.findByRole('heading', { name: 'Options near DT4 8XX' })).toBeInTheDocument();
    expect(screen.getByText('Same services as the list. Sorted by travel time. Not ranked.')).toBeInTheDocument();
    // The segmented control is a row of links: the Map link is the one on screen.
    expect(byEl('ADV-MAP-TOGGLE-MAP')).toHaveAttribute('aria-current', 'page');
  });

  it('the List link returns to the options list', async () => {
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));
    await screen.findByRole('heading', { name: 'Options near DT4 8XX' });

    expect(byEl('ADV-MAP-TOGGLE-LIST')).toHaveAttribute('href', '/advisor/case/4821/options');
  });

  it('says in one line who the options are for: age, postcode, needs and how soon (Map board)', async () => {
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));
    await screen.findByRole('heading', { name: 'Options near DT4 8XX' });

    expect(await screen.findByText('80+ · DT4 8XX · Frailty · Within 2 hrs')).toBeInTheDocument();
  });

  it('puts the map first and the same services as a list beside it, each with an Open link to its request', async () => {
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));
    await screen.findByRole('heading', { name: 'Options near DT4 8XX' });

    const map = screen.getByRole('region', { name: 'Map of options near DT4 8XX' });
    const list = screen.getByRole('region', { name: 'The same services as a list' });
    // Phone: the map is above the list, so it comes first in the page.
    expect(map.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(list).getByRole('link', { name: 'Open UCR West' })).toHaveAttribute('href', '/advisor/case/4821/options?service=svc-ucr-west');
    expect(within(list).getAllByRole('link', { name: /^Open / })).toHaveLength(4);
    expect(within(list).getByText('Accepting · 4')).toBeInTheDocument();
    expect(within(list).getByText('Same services as the list. Sorted by travel time. Not ranked.')).toBeInTheDocument();
  });

  it('a postcode that is not found shows the postcode-not-found card, not the map', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(notFound())));
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));

    expect(await screen.findByRole('heading', { level: 1, name: 'We could not place that postcode in your area' })).toBeInTheDocument();
    expect(document.querySelector('[data-el="ADV-MAP-PIN-SVC-UCR-WEST"]')).toBeNull();
  });

  it('a postcode outside the area shows the outside-area state', async () => {
    server.use(http.get('/api/bff/cases/:ref/options', () => HttpResponse.json(outOfArea())));
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'No service covers this area' })).toBeInTheDocument());
  });
});

function notFound() {
  return { notFound: true, outOfArea: false, patientArea: null, options: [], notSuitable: [] };
}

function outOfArea() {
  return { notFound: false, outOfArea: true, patientArea: null, options: [], notSuitable: [] };
}

describe('map page: the coverage layer (DEC-1372)', () => {
  it('opens with the "Who covers this area" layer off by default, and on for ?layer=coverage', async () => {
    const { unmount } = render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({}) }));
    expect(await screen.findByRole('button', { name: 'Who covers this area' })).toHaveAttribute('aria-pressed', 'false');
    unmount();
    render(await MapPage({ params: Promise.resolve({ ref: '4821' }), searchParams: Promise.resolve({ layer: 'coverage' }) }));
    expect(await screen.findByRole('button', { name: 'Who covers this area' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: 'Key' })).toBeInTheDocument();
  });
});
