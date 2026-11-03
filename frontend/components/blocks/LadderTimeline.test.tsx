import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LadderTimeline, type LadderStep } from './LadderTimeline';

const steps: LadderStep[] = [
  { id: 's1', time: '12:00', title: 'Text sent', detail: 'To the number ending 4821. Delivered.', state: 'done', short: 'Text' },
  { id: 's2', time: '12:30', title: 'Reminder sent', detail: 'No reply.', state: 'done', short: 'Reminder' },
  { id: 's3', time: '13:00', title: 'Advisor phone task', detail: 'No advisor has picked it up.', state: 'open', short: 'Phone task' },
  { id: 's4', time: '13:30', title: 'Escalated to you', detail: 'The board shows this service as unknown.', state: 'escalated' },
];

describe('LadderTimeline', () => {
  it('is an ordered list with one item per step, in order', () => {
    render(<LadderTimeline label="What has been tried" steps={steps} />);
    const list = screen.getByRole('list', { name: 'What has been tried' });
    expect(list.tagName).toBe('OL');
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent('Text sent');
    expect(items[3]).toHaveTextContent('Escalated to you');
  });

  it('says each step state in words, not only a dot', () => {
    render(<LadderTimeline label="What has been tried" steps={steps} />);
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Done');
    expect(items[1]).toHaveTextContent('Done');
    expect(items[2]).toHaveTextContent('Not done');
    expect(items[3]).toHaveTextContent('Needs you');
    expect(items[2]).toHaveAttribute('data-state', 'open');
  });

  it('shows the time with its title and the detail line', () => {
    render(<LadderTimeline label="What has been tried" steps={steps} />);
    expect(screen.getByText('12:00')).toBeInTheDocument();
    expect(screen.getByText('To the number ending 4821. Delivered.')).toBeInTheDocument();
  });

  it('draws the rail between steps but not after the last', () => {
    render(<LadderTimeline label="What has been tried" steps={steps} />);
    const items = screen.getAllByRole('listitem');
    expect(items[0].querySelector('[data-rail]')).not.toBeNull();
    expect(items[3].querySelector('[data-rail]')).toBeNull();
  });

  it('takes its state words from the caller when given', () => {
    render(<LadderTimeline label="Tried" steps={[{ id: 'a', time: '09:00', title: 'Text', state: 'done' }]} stateWords={{ done: 'Sent' }} />);
    expect(screen.getByRole('listitem')).toHaveTextContent('Sent');
  });

  it('has a one-line form for a phone, with the state in words', () => {
    render(<LadderTimeline label="What has been tried" steps={steps} variant="line" />);
    const list = screen.getByRole('list', { name: 'What has been tried' });
    expect(list.tagName).toBe('OL');
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Text 12:00 done');
    expect(items[2]).toHaveTextContent('Phone task 13:00 not done');
    expect(items[3]).toHaveTextContent('Escalated to you');
    expect(screen.queryByText('To the number ending 4821. Delivered.')).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<LadderTimeline label="What has been tried" steps={steps} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
