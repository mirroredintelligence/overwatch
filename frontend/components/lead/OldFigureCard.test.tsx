import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { OldFigureCard } from './OldFigureCard';

const item = OVERVIEW_SHIFT_LEAD.gettingOld[0];
const NOW = Date.parse('2026-10-30T17:00:00Z');

describe('OldFigureCard', () => {
  it('says when the figure was reported, when it is next due, and that it is getting old', () => {
    render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Reablement' })).toBeInTheDocument();
    expect(
      screen.getByText('Reported 2 hrs 10 min ago. Next due 17:00. On schedule, but the figure is getting old.'),
    ).toBeInTheDocument();
  });

  it('shows the status as a badge with its word', () => {
    render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(screen.getByText('Limited')).toBeInTheDocument();
  });

  it('calls onAsk from "Ask for an update now"', async () => {
    const onAsk = vi.fn();
    render(<OldFigureCard item={item} now={NOW} onAsk={onAsk} />);
    const button = screen.getByRole('button', { name: 'Ask for an update now' });
    expect(button).toHaveAttribute('data-el', 'LEAD-OLD-ASK-BTN');
    await userEvent.click(button);
    expect(onAsk).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations', async () => {
    const { container } = render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
