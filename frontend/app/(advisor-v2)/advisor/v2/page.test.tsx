import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/msw/server';
import AdvisorV2Page from './page';
import ServicesPage from './services/page';

// The Advisor v2 pages (DEC-1362, DEC-1366): one heading, the switch between Capacity and Find a Service, and the
// view the address names. Capacity is the default, as in the design.

const OVERVIEW = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 0, limited: 0, notAccepting: 0, overCapacity: 0, notUpdated: 0 },
  attentionShown: 3,
  underPressure: [],
  underutilised: [],
  services: [],
};

describe('the Advisor v2 landing page', () => {
  it('shows Capacity by default, under one heading and the switch', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    render(await AdvisorV2Page({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole('heading', { level: 1, name: 'Advisor v2' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Capacity' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('region', { name: 'Needs attention' })).toBeInTheDocument();
  });

  it('shows Find a Service for mode=find', async () => {
    render(await AdvisorV2Page({ searchParams: Promise.resolve({ mode: 'find' }) }));
    expect(screen.getByRole('link', { name: 'Find a Service' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByLabelText('Postcode')).toBeInTheDocument();
  });

  it('treats any other mode as Capacity', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    render(await AdvisorV2Page({ searchParams: Promise.resolve({ mode: ['x', 'find'] }) }));
    expect(screen.getByRole('link', { name: 'Capacity' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('the Advisor v2 services page', () => {
  it('has a heading and the chosen state pressed', async () => {
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
    render(await ServicesPage({ searchParams: Promise.resolve({ status: 'limited,bogus' }) }));
    expect(screen.getByRole('heading', { level: 1, name: 'Services' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /Limited/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Accepting/ })).toHaveAttribute('aria-pressed', 'false');
  });

  it('names the area in the address in the breadcrumb, and ignores one that is not shaped like an area or that the organisation does not have (DEC-1375)', async () => {
    const areas = [{ id: 'area-one', name: 'Area One', places: 'Alpha' }];
    server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json({ ...OVERVIEW, areas })));
    const named = render(await ServicesPage({ searchParams: Promise.resolve({ area: 'area-one' }) }));
    expect(await screen.findByText('Area One')).toBeInTheDocument();
    named.unmount();
    render(await ServicesPage({ searchParams: Promise.resolve({ area: '<bad>' }) }));
    expect(await screen.findByText('Services', { selector: '[aria-current="page"]' })).toBeInTheDocument();
  });
});
