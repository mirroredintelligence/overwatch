import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { FigureCard } from './FigureCard';

// Artboards B1, B2, B7, D1 and brief Rule 1: the figure is fixed, same place and size on every step, never animated.

describe('FigureCard', () => {
  it('shows the service as the heading, the label, the reply-by tag, the figure with its unit and when it was recorded', () => {
    render(
      <FigureCard
        service="UCR West"
        label="Capacity update"
        replyBy="10:30"
        figure={3}
        unit="referrals in the next 2 hours"
        recordedAt="08:15"
        recordedNote="Still right?"
        dataEl="FIG"
      />,
    );
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Capacity update')).toBeInTheDocument();
    expect(screen.getByText('Reply by 10:30')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('referrals in the next 2 hours')).toBeInTheDocument();
    expect(screen.getByText('Recorded at 08:15. Still right?')).toBeInTheDocument();
  });

  it('shows "Recorded at" alone when there is no note, and the figure 0 as a number', () => {
    render(<FigureCard service="UCR West" figure={0} unit="referrals" recordedAt="10:12" />);
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('Recorded at 10:12')).toBeInTheDocument();
  });

  it('leaves out the tag, the figure and the recorded line that it is not given', () => {
    render(
      <FigureCard service="UCR West" label="First update">
        <p>How many referrals can you take in the next 2 hours?</p>
      </FigureCard>,
    );
    expect(screen.queryByText(/Reply by/)).toBeNull();
    expect(screen.queryByText(/Recorded at/)).toBeNull();
    expect(screen.getByText('How many referrals can you take in the next 2 hours?')).toBeInTheDocument();
  });

  it('can be a level 2 heading when the page has its own h1', () => {
    render(<FigureCard service="UCR East" headingLevel={2} />);
    expect(screen.getByRole('heading', { level: 2, name: 'UCR East' })).toBeInTheDocument();
  });

  it('marks the figure with a data attribute and keeps the tabular numerals class on the number', () => {
    const { container } = render(<FigureCard service="UCR West" figure={4} unit="referrals" dataEl="FIG" />);
    expect(container.querySelector('[data-el="FIG"]')).not.toBeNull();
    expect(container.querySelector('[data-figure="4"]')).not.toBeNull();
  });

  it('never animates the figure: its style sheet has no transition or animation', () => {
    const css = readFileSync(join(__dirname, 'FigureCard.module.css'), 'utf8');
    expect(css).not.toMatch(/transition|animation|@keyframes|transform/);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <FigureCard service="UCR West" label="Capacity update" replyBy="10:30" figure={3} unit="referrals in the next 2 hours" recordedAt="08:15" />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
