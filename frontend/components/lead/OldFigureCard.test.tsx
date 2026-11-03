import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { OldFigureCard } from './OldFigureCard';

const item = OVERVIEW_SHIFT_LEAD.gettingOld[0];
const NOW = Date.parse('2026-10-30T17:00:00Z');

describe('OldFigureCard', () => {
  it('names the service in a level 3 heading', () => {
    render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(screen.getByRole('heading', { level: 3, name: 'Reablement' })).toBeInTheDocument();
  });

  it('says when the figure was reported, when it is next due, and that it is getting old, in one line', () => {
    render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(
      screen.getByText('Reported 2 hrs 10 min ago · next due 17:00 · on schedule, but the figure is getting old'),
    ).toBeInTheDocument();
  });

  it('shows the status as a tag with its shape and its word', () => {
    const { container } = render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(screen.getByText('Limited')).toBeInTheDocument();
    expect(container.querySelector('[data-status="limited"] svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('calls onAsk from "Ask for an update now"', async () => {
    const onAsk = vi.fn();
    render(<OldFigureCard item={item} now={NOW} onAsk={onAsk} />);
    const button = screen.getByRole('button', { name: 'Ask for an update now' });
    expect(button).toHaveAttribute('data-el', 'LEAD-OLD-ASK-BTN');
    await userEvent.click(button);
    expect(onAsk).toHaveBeenCalledTimes(1);
  });

  it('switches the button off when the page is showing figures it could not refresh', async () => {
    const onAsk = vi.fn();
    render(<OldFigureCard item={item} now={NOW} onAsk={onAsk} disabled />);
    const button = screen.getByRole('button', { name: 'Ask for an update now' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    const { container } = render(<OldFigureCard item={item} now={NOW} onAsk={vi.fn()} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
