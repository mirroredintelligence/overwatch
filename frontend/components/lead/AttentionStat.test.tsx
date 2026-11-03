import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { AttentionStat } from './AttentionStat';

// One of the counters at the top of the shift (the board's "Needs you first"): the figure, what it counts,
// and a few words on why. The figure never animates; urgency is a border, an icon and the words.

describe('AttentionStat', () => {
  it('shows the figure with what it counts and why', () => {
    render(<AttentionStat count={2} label="services to chase" hint="overdue now" />);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('services to chase')).toBeInTheDocument();
    expect(screen.getByText('overdue now')).toBeInTheDocument();
  });

  it('is read as one phrase, figure first', () => {
    render(<AttentionStat count={1} label="report to check" hint="looks wrong" />);
    expect(screen.getByRole('group', { name: '1 report to check, looks wrong' })).toBeInTheDocument();
  });

  it('marks an urgent counter with an icon as well as a border, so colour is not the only sign', () => {
    const { container } = render(<AttentionStat count={2} label="services to chase" hint="overdue now" urgent />);
    expect(screen.getByRole('group')).toHaveAttribute('data-urgent', 'true');
    expect(container.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('is not urgent when the figure is zero', () => {
    const { container } = render(<AttentionStat count={0} label="services to chase" hint="overdue now" urgent />);
    expect(screen.getByRole('group')).not.toHaveAttribute('data-urgent');
    expect(container.querySelector('svg')).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ul>
        <li>
          <AttentionStat count={2} label="services to chase" hint="overdue now" urgent />
        </li>
      </ul>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
