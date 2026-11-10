import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/msw/server';
import Page from './page';

// The advisor's service detail page (DEC-1366): the shared page, linking back to the finder.
describe('the advisor v2 service detail page', () => {
  it('shows the service and links back to the finder', async () => {
    server.use(
      http.get('/api/bff/advisor/services/:id/detail', () =>
        HttpResponse.json({
          serviceId: 'svc-a',
          name: 'Ward A',
          category: 'inpatient-beds',
          status: 'accepting',
          unitLabel: 'beds',
          established: 10,
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
        }),
      ),
    );
    render(await Page({ params: Promise.resolve({ id: 'svc-a' }) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Ward A' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to the finder' })).toHaveAttribute('href', '/advisor/v2');
  });
});
