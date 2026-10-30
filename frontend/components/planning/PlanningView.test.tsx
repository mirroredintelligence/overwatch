import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { PlanningView } from './PlanningView';

const PLANNING = {
  cohort: 'Cohort: age 65+, falls and frailty, within 2 hrs, ambulance crew or care home referrers. Groups under 10 are hidden.',
  referrals: 640,
  bestFitUnavailable: { count: 112, pct: 18 },
  wentElsewhere: 62,
  flows: [{ bestFit: 'Falls team, Weymouth', state: 'full', wentTo: 'Community beds', count: 41, suppressed: false }],
  grid: [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 9, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
  ],
  busiest: { day: 'Thursday', band: '12:00 to 18:00', count: 9 },
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
