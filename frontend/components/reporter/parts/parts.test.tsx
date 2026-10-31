import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Panel, StatusMark, StepCards, SummaryRows } from './index';

// The shared reporter page parts (artboards Reporter, OnboardReporter1/2, ReporterApp1/2).

describe('StatusMark', () => {
  it('is a picture only: hidden from a screen reader, with the tone as a data attribute', () => {
    const { container } = render(<StatusMark tone="done" dataEl="MARK" />);
    const mark = container.querySelector('[data-el="MARK"]');
    expect(mark).toHaveAttribute('aria-hidden', 'true');
    expect(mark).toHaveAttribute('data-tone', 'done');
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('draws a different shape for done and closed, so the two are not told apart by colour alone', () => {
    const done = render(<StatusMark tone="done" />).container.querySelector('svg')?.innerHTML;
    const closed = render(<StatusMark tone="closed" />).container.querySelector('svg')?.innerHTML;
    expect(done).toContain('M9.5 15.5');
    expect(closed).toContain('stroke-dasharray');
    expect(done).not.toEqual(closed);
  });
});

describe('Panel', () => {
  it('shows its words as one boxed paragraph', () => {
    render(<Panel dataEl="PANEL">Next update due 12:00</Panel>);
    expect(screen.getByText('Next update due 12:00')).toHaveAttribute('data-el', 'PANEL');
  });
});

describe('StepCards', () => {
  const steps = [
    { key: 'a', title: 'Check your number', hint: '30 seconds' },
    { key: 'b', title: 'Create a PIN' },
  ];

  it('is an ordered list with a title and, when given, a line under each step', async () => {
    const { container } = render(<StepCards label="Set-up steps" steps={steps} />);
    const items = within(screen.getByRole('list', { name: 'Set-up steps' })).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Check your number');
    expect(items[0]).toHaveTextContent('30 seconds');
    expect(items[1]).toHaveTextContent('Create a PIN');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('hides the number in the circle from a screen reader: the list already says the order', () => {
    const { container } = render(<StepCards steps={steps} />);
    const numbers = container.querySelectorAll('li > span[aria-hidden="true"]');
    expect(Array.from(numbers).map((n) => n.textContent)).toEqual(['1', '2']);
  });
});

describe('SummaryRows', () => {
  it('pairs each label with its value in a description list', async () => {
    const { container } = render(
      <SummaryRows
        rows={[
          { label: 'Service', value: 'UCR West' },
          { label: 'Phone', value: '07xxx xxx456' },
        ]}
      />,
    );
    expect(container.querySelectorAll('dt')).toHaveLength(2);
    expect(screen.getByText('Service').nextElementSibling).toHaveTextContent('UCR West');
    expect(screen.getByText('Phone').nextElementSibling).toHaveTextContent('07xxx xxx456');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
