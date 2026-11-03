import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { TimelineList } from './TimelineList';

const ITEMS = [
  { id: '1', title: 'Signed in', detail: 'Platform operator', time: '2 Nov 09:02', at: '2026-11-02T09:02:00Z' },
  { id: '2', title: 'Asked to look in', detail: 'SR-0412', time: 'Today 14:12', tone: 'attention' as const },
  { id: '3', title: 'Access ended', time: 'Today 15:31', tone: 'past' as const },
];

describe('TimelineList', () => {
  it('is a labelled list with title, detail and time for each entry', () => {
    render(<TimelineList label="Entries" items={ITEMS} />);
    const list = screen.getByRole('list', { name: 'Entries' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByText('Signed in')).toBeInTheDocument();
    expect(screen.getByText('Platform operator')).toBeInTheDocument();
    expect(screen.getByText('2 Nov 09:02')).toBeInTheDocument();
  });

  it('puts a machine-readable time on the time element when given', () => {
    render(<TimelineList label="Entries" items={ITEMS} />);
    expect(screen.getByText('2 Nov 09:02').closest('time')).toHaveAttribute('datetime', '2026-11-02T09:02:00Z');
  });

  it('marks the tone of each entry and the line variant', () => {
    const { container } = render(<TimelineList label="Entries" items={ITEMS} line />);
    expect(screen.getByText('Asked to look in').closest('li')).toHaveAttribute('data-tone', 'attention');
    expect(screen.getByText('Access ended').closest('li')).toHaveAttribute('data-tone', 'past');
    expect(screen.getByText('Signed in').closest('li')).toHaveAttribute('data-tone', 'normal');
    expect(container.querySelector('[data-line="true"]')).not.toBeNull();
  });

  it('draws the dots as decoration', () => {
    const { container } = render(<TimelineList label="Entries" items={ITEMS} />);
    const dots = container.querySelectorAll('[data-dot]');
    expect(dots).toHaveLength(3);
    dots.forEach((d) => expect(d).toHaveAttribute('aria-hidden', 'true'));
  });

  it('has no axe violations', async () => {
    const { container } = render(<TimelineList label="Entries" items={ITEMS} line />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
