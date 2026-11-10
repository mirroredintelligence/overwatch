import type { ReactElement } from 'react';
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AdvisorWorkspace } from '@/components/workspace/AdvisorWorkspace';
import { WorkspaceProvider } from '@/components/workspace/WorkspaceProvider';
import { server } from '@/test/msw/server';
import AdvisorV2Page from './page';
import ServicesPage from './services/page';

// The Advisor v2 pages (DEC-1362, DEC-1366, WS-RTE): Capacity is the default and runs in the workspace frame with the
// switch; mode=find is the find workspace, which supplies its own frame; the services page runs in the frame too.

// The navigation hooks the find workspace reads: the search string is set per test, the router is a pair of spies.
const nav = vi.hoisted(() => ({ search: '', push: vi.fn(), replace: vi.fn() }));

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation');
  return {
    ...actual,
    useRouter: () => ({ push: nav.push, replace: nav.replace }),
    useSearchParams: () => new URLSearchParams(nav.search),
    usePathname: () => '/advisor/v2',
  };
});

// The find workspace is passed through unchanged, so the real one renders, except where a test sets an implementation once.
vi.mock('@/components/workspace/AdvisorWorkspace', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/workspace/AdvisorWorkspace')>();
  return { ...actual, AdvisorWorkspace: vi.fn(actual.AdvisorWorkspace) };
});

const OVERVIEW = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 0, limited: 0, notAccepting: 0, overCapacity: 0, notUpdated: 0 },
  attentionShown: 3,
  underPressure: [],
  underutilised: [],
  services: [],
};

// Renders the awaited page inside the provider the layout gives it.
async function renderPage(page: Promise<ReactElement>) {
  return render(<WorkspaceProvider role="advisor-v2">{await page}</WorkspaceProvider>);
}

beforeEach(() => {
  nav.search = '';
  nav.push.mockClear();
  nav.replace.mockClear();
});

describe('the Advisor v2 landing page', () => {
  it('shows Capacity by default, in the frame, with the switch', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({}) }));
    expect(within(screen.getByRole('banner')).getByText('Capacity')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Capacity' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('region', { name: 'Needs attention' })).toBeInTheDocument();
  });

  it('WS-RTE-T01 Capacity: with no mode, or mode=capacity, the frame is titled Capacity, with the switch and CapacityOverview, and no assistant', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    const first = await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({}) }));
    expect(within(screen.getByRole('banner')).getByText('Capacity')).toBeInTheDocument();
    const switcher = within(screen.getByRole('navigation', { name: 'Advisor view' }));
    expect(switcher.getByRole('link', { name: 'Capacity' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('region', { name: 'Needs attention' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
    first.unmount();

    await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({ mode: 'capacity' }) }));
    expect(within(screen.getByRole('banner')).getByText('Capacity')).toBeInTheDocument();
    expect(await screen.findByRole('region', { name: 'Needs attention' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
  });

  it('shows the find workspace for mode=find, with its postcode field and no switch', async () => {
    nav.search = 'mode=find';
    await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({ mode: 'find' }) }));
    expect(within(screen.getByRole('banner')).getByText('Find a service')).toBeInTheDocument();
    expect(screen.getByLabelText('Postcode')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Advisor view' })).toBeNull();
  });

  it('WS-RTE-T02 mode=find renders AdvisorWorkspace and nothing else', async () => {
    vi.mocked(AdvisorWorkspace).mockImplementationOnce(() => <p>Find workspace stub</p>);
    await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({ mode: 'find' }) }));
    expect(screen.getByText('Find workspace stub')).toBeInTheDocument();
    expect(AdvisorWorkspace).toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: 'Patient criteria' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Needs attention' })).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Advisor view' })).toBeNull();
    expect(screen.queryByRole('banner')).toBeNull();
  });

  it('WS-RTE-T04 the capacity and find outputs each contain exactly one main landmark', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    const capacity = await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({}) }));
    expect(await screen.findByRole('region', { name: 'Needs attention' })).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
    capacity.unmount();

    nav.search = 'mode=find';
    await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({ mode: 'find' }) }));
    expect(await screen.findByLabelText('Postcode')).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });

  it('treats any other mode as Capacity', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    await renderPage(AdvisorV2Page({ searchParams: Promise.resolve({ mode: ['x', 'find'] }) }));
    expect(screen.getByRole('link', { name: 'Capacity' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('the Advisor v2 services page', () => {
  it('has the title Services in the frame and the chosen state pressed', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    await renderPage(ServicesPage({ searchParams: Promise.resolve({ status: 'limited,bogus' }) }));
    expect(within(screen.getByRole('banner')).getByText('Services')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /Limited/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Accepting/ })).toHaveAttribute('aria-pressed', 'false');
  });

  it('names the area in the address in the breadcrumb, and ignores one that is not shaped like an area or that the organisation does not have (DEC-1375)', async () => {
    const areas = [{ id: 'area-one', name: 'Area One', places: 'Alpha' }];
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json({ ...OVERVIEW, areas })));
    const named = await renderPage(ServicesPage({ searchParams: Promise.resolve({ area: 'area-one' }) }));
    expect(await screen.findByText('Area One')).toBeInTheDocument();
    named.unmount();
    await renderPage(ServicesPage({ searchParams: Promise.resolve({ area: '<bad>' }) }));
    expect(await screen.findByText('Services', { selector: '[aria-current="page"]' })).toBeInTheDocument();
  });
});
