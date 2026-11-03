import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { PathRow } from '@/lib/console/insight';
import { PathsTab } from './PathsTab';

const COMMON: PathRow[] = [
  { route: '/case/[ref]', sessions: 212, medianSeconds: 80, suppressed: false },
  { route: '/case/[ref]/options', sessions: 198, medianSeconds: 48, suppressed: false },
  { route: '/help', sessions: null, medianSeconds: null, suppressed: true },
];

const UTURNS: PathRow[] = [{ route: '/case/[ref]/options to /case/[ref]', sessions: 18, medianSeconds: null, suppressed: false }];

describe('PathsTab', () => {
  it('is one panel named Paths, with the common routes as a table', () => {
    render(<PathsTab mostCommon={COMMON} uTurns={UTURNS} unused={[]} />);

    const panel = screen.getByRole('region', { name: 'Paths' });
    expect(within(panel).getByRole('table', { name: /most common routes/i })).toBeInTheDocument();
  });

  it('lists each route with its sessions and its median time, and a route under 10 as fewer than 10', () => {
    render(<PathsTab mostCommon={COMMON} uTurns={UTURNS} unused={[]} />);

    const table = screen.getByRole('table', { name: /most common routes/i });
    expect(within(table).getByRole('columnheader', { name: 'Median time' })).toBeInTheDocument();
    expect(within(table).getByRole('row', { name: /\/case\/\[ref\]\/options/ })).toHaveTextContent('198');
    expect(within(table).getByRole('row', { name: /\/case\/\[ref\]\/options/ })).toHaveTextContent('48 s');
    expect(within(table).getByRole('row', { name: /\/help/ })).toHaveTextContent('fewer than 10');
  });

  it('lists the U-turns with the count after the route', () => {
    render(<PathsTab mostCommon={COMMON} uTurns={UTURNS} unused={[]} />);

    expect(screen.getByRole('heading', { name: 'U-turns: left within 5 s' })).toBeInTheDocument();
    expect(screen.getByText('/case/[ref]/options to /case/[ref]: 18')).toBeInTheDocument();
  });

  it('lists the controls nobody used this week by name', () => {
    render(<PathsTab mostCommon={COMMON} uTurns={[]} unused={['ADV-SCORE-MANCHESTER-CHIP']} />);

    expect(screen.getByRole('heading', { name: 'Never used this week' })).toBeInTheDocument();
    expect(screen.getByText('ADV-SCORE-MANCHESTER-CHIP')).toBeInTheDocument();
  });

  it('says the unused controls are not measured when the back end cannot say', () => {
    render(<PathsTab mostCommon={COMMON} uTurns={[]} unused={null} />);

    expect(screen.getByText('Not measured yet: this needs the list of every control.')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<PathsTab mostCommon={COMMON} uTurns={UTURNS} unused={null} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
