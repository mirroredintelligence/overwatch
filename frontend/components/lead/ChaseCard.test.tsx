import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { ChaseCard, LadderTimeline } from './ChaseCard';

const item = OVERVIEW_SHIFT_LEAD.chasing[0];

describe('ChaseCard', () => {
  it('says when the report was due, how overdue it is, and the last figure', () => {
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Virtual ward' })).toBeInTheDocument();
    expect(
      screen.getByText('Report was due 12:00. Overdue by 2 hrs 12 min. Last figure: 3 beds free.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Shown as unknown on the board')).toBeInTheDocument();
  });

  it('lists the ladder as four ordered steps, each with its time, its words and its state', () => {
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} />);
    const rows = screen.getAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual([
      '12:00 · Text sent Done.',
      '12:30 · Reminder sent Done.',
      '13:00 · Advisor phone task Not done.',
      '13:30 · Escalated to you Not done.',
    ]);
    expect(screen.getByRole('list')).toHaveAttribute('data-el', 'LEAD-CHASE-LADDER');
  });

  it('carries the ladder as one line of text for a phone', () => {
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} />);
    expect(
      screen.getByText('Text 12:00 done · Reminder 12:30 done · Phone task not done · Escalated to you'),
    ).toBeInTheDocument();
  });

  it('calls onEnterPhoned from "Enter what they told me by phone"', async () => {
    const onEnterPhoned = vi.fn();
    render(<ChaseCard item={item} onEnterPhoned={onEnterPhoned} onRemind={vi.fn()} />);
    const button = screen.getByRole('button', { name: 'Enter what they told me by phone' });
    expect(button).toHaveAttribute('data-el', 'LEAD-CHASE-PHONED-BTN');
    await userEvent.click(button);
    expect(onEnterPhoned).toHaveBeenCalledTimes(1);
  });

  it('calls onRemind from "Send reminder again"', async () => {
    const onRemind = vi.fn();
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={onRemind} />);
    await userEvent.click(screen.getByRole('button', { name: 'Send reminder again' }));
    expect(onRemind).toHaveBeenCalledTimes(1);
  });

  it('links "Change number" to the number form for this service', () => {
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} />);
    const link = screen.getByRole('link', { name: 'Change number' });
    expect(link).toHaveAttribute('href', '/lead/reporters/number?service=s-virtual-ward');
    expect(link).toHaveAttribute('data-el', 'LEAD-CHASE-NUMBER-LINK');
  });

  it('shows no Close button and no suspend link on a card in the list', () => {
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Suspend this service' })).toBeNull();
  });

  it('calls onClose from "Close" on the open card', async () => {
    const onClose = vi.fn();
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} onClose={onClose} />);
    const button = screen.getByRole('button', { name: 'Close' });
    expect(button).toHaveAttribute('data-el', 'LEAD-CHASE-CLOSE-BTN');
    await userEvent.click(button);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('links "Suspend this service" on the open card to the suspend form', () => {
    render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('link', { name: 'Suspend this service' })).toHaveAttribute(
      'href',
      '/lead/services/s-virtual-ward/suspend',
    );
  });

  it('has no axe violations', async () => {
    const { container } = render(<ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations on the open card', async () => {
    const { container } = render(
      <ChaseCard item={item} onEnterPhoned={vi.fn()} onRemind={vi.fn()} onClose={vi.fn()} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('LadderTimeline', () => {
  it('gives each step its state in words, not only a shape', () => {
    render(<LadderTimeline ladder={item.ladder} />);
    const steps = screen.getAllByRole('listitem');
    expect(steps).toHaveLength(4);
    expect(steps[0]).toHaveTextContent('Done.');
    expect(steps[2]).toHaveTextContent('Not done.');
  });
});
