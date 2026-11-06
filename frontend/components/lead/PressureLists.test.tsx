import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';

const PRESSURE = OVERVIEW_SHIFT_LEAD.underPressure ?? [];
const UNDERUSED = OVERVIEW_SHIFT_LEAD.underutilised ?? [];
import { UnderPressureList, UnderutilisedList } from './PressureLists';

// Under pressure and Underutilised (DEC-1343).

describe('UnderPressureList', () => {
  it('lists each service with its status word, its reason and its share used', () => {
    render(<UnderPressureList items={PRESSURE} />);
    const list = screen.getByRole('region', { name: 'Under pressure' });
    expect(within(list).getByText('Hospital at home')).toBeInTheDocument();
    expect(within(list).getByText('2 over normal capacity · 120% used')).toBeInTheDocument();
    expect(within(list).getByText('Over capacity')).toBeInTheDocument();
  });

  it('says Unknown, with the words to confirm first, for an old figure, and no percentage', () => {
    render(<UnderPressureList items={PRESSURE} />);
    expect(screen.getByText('Figure is old. Confirm before redirecting demand. · Unknown')).toBeInTheDocument();
  });

  it('says so when no service is under pressure', () => {
    render(<UnderPressureList items={[]} />);
    expect(screen.getByText('No service is under pressure.')).toBeInTheDocument();
  });

  it('shows the first five and says how many more', () => {
    const many = Array.from({ length: 7 }, (_, i) => ({
      serviceId: `s${i}`,
      name: `Service ${i}`,
      status: 'limited' as const,
      reason: 'Limited',
      usedPercent: 90,
    }));
    render(<UnderPressureList items={many} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
    expect(screen.getByText('and 2 more')).toBeInTheDocument();
  });
});

describe('UnderutilisedList', () => {
  it('lists a service with its share used and what is spare, and says it is not a recommendation', () => {
    render(<UnderutilisedList items={UNDERUSED} />);
    expect(screen.getByText('20% used · 8 beds free')).toBeInTheDocument();
    expect(screen.getByText(/not a recommendation of where to send a patient/)).toBeInTheDocument();
  });

  it('says so when no service has spare room on a current figure', () => {
    render(<UnderutilisedList items={[]} />);
    expect(screen.getByText('No service has spare room on a current figure.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <>
        <UnderPressureList items={PRESSURE} />
        <UnderutilisedList items={UNDERUSED} />
      </>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
