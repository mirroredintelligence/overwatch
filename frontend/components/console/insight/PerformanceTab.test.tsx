import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { Slow, Vital } from '@/lib/console/insight';
import { PerformanceTab } from './PerformanceTab';

const VITALS: Vital[] = [
  { measure: 'Largest contentful paint', metric: 'lcp', device: 'desktop', p75: 2100, budget: 2500, unit: 'ms', suppressed: false },
  { measure: 'Interaction to next paint', metric: 'inp', device: 'phone', p75: 240, budget: 200, unit: 'ms', suppressed: false },
  { measure: 'Cumulative layout shift', metric: 'cls', device: 'phone', p75: null, budget: 0.1, unit: 'score', suppressed: true },
];

const ROUTES: Slow[] = [{ name: 'POST /api/bff/bookings', p95Ms: 2400 }];
const QUERIES: Slow[] = [{ name: 'Q-TASK-BOOK-CREATE', p95Ms: 1200 }];

describe('PerformanceTab', () => {
  it('is one panel named Performance, with the vitals as a table', () => {
    render(<PerformanceTab vitals={VITALS} slowestRoutes={ROUTES} slowestQueries={QUERIES} promptToBoard={null} />);

    const panel = screen.getByRole('region', { name: 'Performance' });
    expect(within(panel).getByRole('table', { name: 'Web vitals table' })).toBeInTheDocument();
  });

  it('marks each status with a shape and its word: within budget is a dot, over budget a triangle', () => {
    render(<PerformanceTab vitals={VITALS} slowestRoutes={ROUTES} slowestQueries={QUERIES} promptToBoard={null} />);

    const table = screen.getByRole('table', { name: 'Web vitals table' });
    const within_ = within(table).getByRole('row', { name: /Largest contentful paint/ });
    expect(within_).toHaveTextContent('Within budget');
    expect(within_.querySelector('[aria-hidden="true"]')).toHaveTextContent('●');
    const over = within(table).getByRole('row', { name: /Interaction to next paint/ });
    expect(over).toHaveTextContent('Over budget');
    expect(over.querySelector('[aria-hidden="true"]')).toHaveTextContent('▲');
    expect(over).toHaveAttribute('data-flagged');
    expect(within_).not.toHaveAttribute('data-flagged');
  });

  it('shows a vital under 10 sessions as fewer than 10, with no status and no shape', () => {
    render(<PerformanceTab vitals={VITALS} slowestRoutes={ROUTES} slowestQueries={QUERIES} promptToBoard={null} />);

    const row = within(screen.getByRole('table', { name: 'Web vitals table' })).getByRole('row', { name: /Cumulative layout shift/ });
    expect(row).toHaveTextContent('fewer than 10');
    expect(row.querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it('lists the slowest routes and queries with their p95', () => {
    render(<PerformanceTab vitals={VITALS} slowestRoutes={ROUTES} slowestQueries={QUERIES} promptToBoard={null} />);

    expect(screen.getByText('POST /api/bff/bookings: p95 2400 ms')).toBeInTheDocument();
    expect(screen.getByText('Q-TASK-BOOK-CREATE: p95 1200 ms')).toBeInTheDocument();
  });

  it('gives prompt to board in the board words, system time and human time', () => {
    render(
      <PerformanceTab
        vitals={[]}
        slowestRoutes={[]}
        slowestQueries={[]}
        promptToBoard={{ systemSeconds: 4, humanMinutes: 8 }}
      />,
    );

    expect(screen.getByText('Prompt to board: system time 4 s, human time 8 min.')).toBeInTheDocument();
  });

  it('says prompt to board is not measured when the back end has no figure', () => {
    render(<PerformanceTab vitals={[]} slowestRoutes={[]} slowestQueries={[]} promptToBoard={null} />);

    expect(screen.getByText('Prompt to board: not measured yet.')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(
      <PerformanceTab vitals={VITALS} slowestRoutes={ROUTES} slowestQueries={QUERIES} promptToBoard={null} />,
    );

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
