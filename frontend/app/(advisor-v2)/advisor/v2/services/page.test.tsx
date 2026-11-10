import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { V2Services } from '@/components/advisor-v2/V2Services';
import { WorkspaceProvider } from '@/components/workspace/WorkspaceProvider';
import { server } from '@/test/msw/server';
import ServicesPage from './page';

// The services page (WS-RTE) runs in the workspace frame titled Services, with a Back link to Capacity. The list itself
// is V2Services, passed through unchanged so its props can be checked.

vi.mock('@/components/advisor-v2/V2Services', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/advisor-v2/V2Services')>();
  return { ...actual, V2Services: vi.fn(actual.V2Services) };
});

const OVERVIEW = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 0, limited: 1, notAccepting: 0, overCapacity: 0, notUpdated: 0 },
  attentionShown: 3,
  underPressure: [],
  underutilised: [],
  areas: [],
  services: [
    {
      serviceId: 'b',
      name: 'Pressed B',
      category: 'inpatient-beds',
      status: 'limited',
      effectiveAvailable: 1,
      overBy: null,
      unitLabel: 'beds free',
      reportedAt: '2026-11-10T09:00:00Z',
      figureUnavailable: true,
      lastFigure: 1,
      districts: ['DT4'],
    },
  ],
};

beforeEach(() => {
  vi.mocked(V2Services).mockClear();
  server.use(http.get('/api/bff/advisor-v2/capacity', () => HttpResponse.json(OVERVIEW)));
});

describe('the Advisor v2 services page in the workspace', () => {
  it('WS-RTE-T03 renders V2Services inside the frame titled Services, with a Back link to /advisor/v2 and the same props', async () => {
    const page = await ServicesPage({
      searchParams: Promise.resolve({ status: 'limited', group: 'inpatient-beds', district: 'DT4', area: 'area-one' }),
    });
    render(<WorkspaceProvider role="advisor-v2">{page}</WorkspaceProvider>);
    const banner = screen.getByRole('banner');
    expect(within(banner).getByText('Services')).toBeInTheDocument();
    expect(within(banner).getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/advisor/v2');
    expect(vi.mocked(V2Services).mock.calls[0]?.[0]).toMatchObject({
      initial: ['limited'],
      group: 'inpatient-beds',
      district: 'DT4',
      area: 'area-one',
    });
    expect(await screen.findByText('Listed by name, not ranked.')).toBeInTheDocument();
  });

  it('WS-RTE-T04 the services output contains exactly one main landmark', async () => {
    const page = await ServicesPage({ searchParams: Promise.resolve({}) });
    render(<WorkspaceProvider role="advisor-v2">{page}</WorkspaceProvider>);
    expect(await screen.findByText('Listed by name, not ranked.')).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });
});
