import { byEl } from '@/test/el';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CallSteps } from './CallSteps';

describe('CallSteps (W10, step bar of the Call board)', () => {
  it('lists Needs, Options, Request and Outcome in order', () => {
    render(<CallSteps current="needs" />);

    const list = screen.getByRole('list', { name: 'Call steps' });
    const items = within(list).getAllByRole('listitem');
    expect(items.map((item) => item.querySelector('[data-part="label"]')?.textContent)).toEqual([
      'Needs',
      'Options',
      'Request',
      'Outcome',
    ]);
  });

  it('numbers the steps 1 to 4 in a badge that readers skip', () => {
    render(<CallSteps current="options" />);

    const items = within(screen.getByRole('list', { name: 'Call steps' })).getAllByRole('listitem');
    items.forEach((item, index) => {
      const badge = within(item).getByText(String(index + 1));
      expect(badge).toHaveAttribute('aria-hidden', 'true');
      expect(badge).toHaveAttribute('data-part', 'number');
    });
  });

  it('marks Needs done, gives Options aria-current and shows the options Now and Next text', () => {
    render(<CallSteps current="options" />);

    const needs = byEl('ADV-STEP-NEEDS');
    const options = byEl('ADV-STEP-OPTIONS');
    expect(needs).toHaveAttribute('data-state', 'done');
    expect(needs).not.toHaveAttribute('aria-current');
    expect(options).toHaveAttribute('aria-current', 'step');
    expect(screen.getByText('Now: compare the options and check the criteria.')).toBeInTheDocument();
    expect(screen.getByText('Next: request a booking from the one you choose.')).toBeInTheDocument();
  });

  it('says Done in words on a finished step, and only on those', () => {
    render(<CallSteps current="request" />);

    expect(within(byEl('ADV-STEP-NEEDS')).getByText('Done')).toBeInTheDocument();
    expect(within(byEl('ADV-STEP-OPTIONS')).getByText('Done')).toBeInTheDocument();
    expect(within(byEl('ADV-STEP-REQUEST')).queryByText('Done')).toBeNull();
    expect(within(byEl('ADV-STEP-OUTCOME')).queryByText('Done')).toBeNull();
  });

  it('exactly one step is current for each value and steps before it are done', () => {
    const steps = ['needs', 'options', 'request', 'outcome'] as const;
    for (const [index, current] of steps.entries()) {
      const { unmount } = render(<CallSteps current={current} />);
      const currentItems = document.querySelectorAll('[aria-current="step"]');
      expect(currentItems).toHaveLength(1);
      expect(currentItems[0]).toHaveAttribute('data-step', current);
      for (const earlier of steps.slice(0, index)) {
        expect(byEl(`ADV-STEP-${earlier.toUpperCase()}`)).toHaveAttribute('data-state', 'done');
      }
      for (const later of steps.slice(index + 1)) {
        expect(byEl(`ADV-STEP-${later.toUpperCase()}`)).toHaveAttribute('data-state', 'todo');
      }
      unmount();
    }
  });

  it('shows the Needs wording for the first step', () => {
    render(<CallSteps current="needs" />);

    expect(screen.getByText('Now: capture age, postcode, needs and how soon.')).toBeInTheDocument();
    expect(screen.getByText('Next: see the options.')).toBeInTheDocument();
  });

  it('takes Now and Next from props when they are given', () => {
    render(<CallSteps current="request" now="Now: a custom line." next="Next: another line." />);

    expect(screen.getByText('Now: a custom line.')).toBeInTheDocument();
    expect(screen.getByText('Next: another line.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<CallSteps current="options" />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
