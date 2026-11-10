import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { WorkspaceProvider } from '@/components/workspace/WorkspaceProvider';
import { server } from '@/test/msw/server';
import Page from './page';

// The advisor's service detail page (DEC-1367, WS-SVC): the shared detail inside the workspace frame, linking back to
// the results list. The page is rendered inside the provider the layout gives it.
const DETAIL = {
  serviceId: 'svc-a',
  name: 'Ward A',
  category: 'inpatient-beds',
  status: 'accepting',
  unitLabel: 'beds',
  established: 10,
  used: 6,
  effectiveAvailable: 4,
  overBy: null,
  lastFigure: 4,
  reportedAt: null,
  nextDueAt: null,
  cadence: null,
  overdue: false,
  staleWarning: false,
  dataAgeSeconds: null,
  phone: null,
  openingHours: [],
  accepts: null,
  excludes: null,
  ageMin: null,
  ageMax: null,
  districts: [],
};

async function renderPage(id: string) {
  const page = await Page({ params: Promise.resolve({ id }) });
  return render(<WorkspaceProvider role="advisor-v2">{page}</WorkspaceProvider>);
}

describe('the advisor v2 service detail page', () => {
  it('WS-SVC-T05 the page renders the service for the id from its params', async () => {
    const requested: string[] = [];
    server.use(
      http.get('/api/bff/advisor/services/:id/detail', ({ params }) => {
        requested.push(String(params.id));
        return HttpResponse.json(DETAIL);
      }),
    );
    await renderPage('svc-a');
    expect(screen.getByText('Service detail')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { level: 1, name: 'Ward A' })).toBeInTheDocument();
    expect(requested).toEqual(['svc-a']);
  });

  it('shows the service and links back to the results', async () => {
    server.use(http.get('/api/bff/advisor/services/:id/detail', () => HttpResponse.json(DETAIL)));
    await renderPage('svc-a');
    expect(await screen.findByRole('heading', { level: 1, name: 'Ward A' })).toBeInTheDocument();
    // The thread's chip has the same name and href, so the service's own back control is found on the canvas.
    const canvas = screen.getByRole('main', { name: 'Canvas' });
    expect(within(canvas).getByRole('link', { name: 'Back to results' })).toHaveAttribute(
      'href',
      '/advisor/v2?mode=find&view=list',
    );
  });
});
