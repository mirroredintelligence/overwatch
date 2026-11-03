import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CoverUntil, untilBody } from './CoverUntil';

// Artboard B7 (3): "Until" with three chips, the chosen one filled. Still three real radio buttons.

describe('CoverUntil', () => {
  it('is a group called Until with three radio choices', () => {
    render(<CoverUntil until="tonight" date="" onUntil={() => {}} onDate={() => {}} name="until" />);
    const group = screen.getByRole('group', { name: 'Until' });
    expect(group).toBeInTheDocument();
    expect(screen.getAllByRole('radio').map((r) => r.parentElement?.textContent?.trim())).toEqual(['Tonight', 'This week', 'A date']);
    expect(screen.getByRole('radio', { name: 'Tonight' })).toBeChecked();
  });

  it('draws each choice as a chip and marks the chosen one, with a tick so it is not told by colour alone', () => {
    const { container } = render(<CoverUntil until="this-week" date="" onUntil={() => {}} onDate={() => {}} name="until" />);
    const chips = container.querySelectorAll('[data-chip]');
    expect(chips).toHaveLength(3);
    expect(Array.from(chips).map((c) => c.getAttribute('data-selected'))).toEqual(['false', 'true', 'false']);
    expect(chips[1].querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(chips[0].querySelector('svg')).toBeNull();
  });

  it('reports the choice made, and by keyboard', async () => {
    const user = userEvent.setup();
    const onUntil = vi.fn();
    render(<CoverUntil until="tonight" date="" onUntil={onUntil} onDate={() => {}} name="until" />);
    await user.click(screen.getByRole('radio', { name: 'A date' }));
    expect(onUntil).toHaveBeenCalledWith('date');
    screen.getByRole('radio', { name: 'Tonight' }).focus();
    await user.keyboard('{ArrowDown}');
    expect(onUntil).toHaveBeenCalledWith('this-week');
  });

  it('shows the date field only for "A date"', async () => {
    const onDate = vi.fn();
    const { rerender } = render(<CoverUntil until="tonight" date="" onUntil={() => {}} onDate={onDate} name="until" />);
    expect(screen.queryByLabelText('Cover until date')).toBeNull();
    rerender(<CoverUntil until="date" date="" onUntil={() => {}} onDate={onDate} name="until" />);
    expect(screen.getByLabelText('Cover until date')).toBeInTheDocument();
  });

  it('builds the request body as before', () => {
    expect(untilBody('tonight', '')).toEqual({ until: 'tonight' });
    expect(untilBody('date', '')).toBeNull();
    expect(untilBody('date', '2026-11-05')).toEqual({ until: 'date', date: '2026-11-05' });
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<CoverUntil until="date" date="2026-11-05" onUntil={() => {}} onDate={() => {}} name="until" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
