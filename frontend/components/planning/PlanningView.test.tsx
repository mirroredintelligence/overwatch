import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { PlanningView } from './PlanningView';

// The answer as `GET /planning` gives it (routes_planning.py): a count under 10 is null and suppressed.
const PLANNING = {
  cohort: 'Cohort: age 65+, falls and frailty, within 2 hrs, ambulance crew or care home referrers. Groups under 10 are hidden.',
  referrals: { count: 640, suppressed: false },
  bestFitUnavailable: { count: 112, pct: 18, suppressed: false },
  wentElsewhere: { count: 62, suppressed: false },
  flows: [{ bestFit: 'Falls team, Weymouth', state: 'full', wentTo: 'Community beds', count: 41, suppressed: false }],
  grid: [
    [null, null, null, null],
    [null, null, null, null],
    [null, null, null, null],
    [null, null, 12, null],
    [null, null, null, null],
    [null, null, null, null],
    [null, null, null, null],
  ],
  busiest: { day: 3, band: 2, count: 12 },
  declinedDespite: [{ service: 'Frailty ward', count: null, suppressed: true }],
};

function answer(seen: string[]) {
  server.use(
    http.get('/api/bff/planning', ({ request }) => {
      seen.push(new URL(request.url).searchParams.get('period') ?? '');
      return HttpResponse.json(PLANNING);
    }),
  );
}

describe('PlanningView with small counts hidden', () => {
  it('says fewer than 10 for a headline the back end withheld, and shows no share for it', async () => {
    server.use(http.get('/api/bff/planning', () => HttpResponse.json({
      ...PLANNING,
      referrals: { count: null, suppressed: true },
      bestFitUnavailable: { count: null, pct: null, suppressed: true },
      wentElsewhere: { count: null, suppressed: true },
      grid: PLANNING.grid.map((row) => row.map(() => null)),
      busiest: null,
      flows: [],
    })));
    render(<PlanningView />);

    expect(await screen.findByText('Fewer than 10 referrals')).toBeInTheDocument();
    expect(screen.getByText(/Fewer than 10 best fit unavailable/)).not.toHaveTextContent('%');
    expect(screen.getByText('Fewer than 10 went to another suitable service')).toBeInTheDocument();
    expect(screen.getByText('No day or time had 10 or more unavailable referrals.')).toBeInTheDocument();
  });

  it('says it could not load, and shows no figure, when the back end fails', async () => {
    server.use(http.get('/api/bff/planning', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<PlanningView />);

    expect(await screen.findByRole('alert')).toHaveTextContent('The planning view could not be loaded. Try again.');
    expect(screen.queryByText(/referrals/)).toBeNull();
  });

  it('reads the busiest cell from the back end\'s answer', async () => {
    answer([]);
    render(<PlanningView />);

    expect(await screen.findByText('Busiest: Thursday 12:00 to 18:00 (12)')).toBeInTheDocument();
  });
});

describe('PlanningView', () => {
  it('asks for the 30-day period when it is chosen', async () => {
    const seen: string[] = [];
    answer(seen);
    render(<PlanningView />);
    await screen.findByText('640 referrals');

    await userEvent.click(screen.getByRole('button', { name: 'Last 30 days' }));

    await waitFor(() => expect(seen).toContain('30d'));
  });

  it('shows the headline figures, the cohort, and the reading note', async () => {
    answer([]);
    render(<PlanningView />);

    expect(await screen.findByText('640 referrals')).toBeInTheDocument();
    expect(screen.getByText(/112 best fit unavailable/)).toHaveTextContent('18%');
    expect(screen.getByText('62 went to another suitable service')).toBeInTheDocument();
    expect(screen.getByText(/They do not show what happened to patients afterwards/)).toBeInTheDocument();
  });

  it('says that the figures are not a league table and are not used to assess advisors, and lists no advisor', async () => {
    answer([]);
    render(<PlanningView />);
    await screen.findByText('640 referrals');

    expect(screen.getByText(/Not a league table and not used to assess advisors/)).toBeInTheDocument();
    expect(screen.queryByText(/advisor [A-Z][a-z]+/)).toBeNull();
  });

  it('passes vitest-axe', async () => {
    answer([]);
    const { container } = render(<PlanningView />);
    await screen.findByText('640 referrals');

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
