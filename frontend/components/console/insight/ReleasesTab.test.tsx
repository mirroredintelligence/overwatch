import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { Measure } from '@/lib/console/insight';
import { changeWord, ReleasesTab } from './ReleasesTab';

const measure = (over: Partial<Measure>): Measure => ({
  measure: 'Friction events per 100 interactions',
  old: 3,
  new: 5.1,
  unit: 'percent',
  review: true,
  ...over,
});

describe('changeWord', () => {
  it('is Slower or Faster for a time and Higher or Lower for a score or a rate', () => {
    expect(changeWord(measure({ unit: 'ms', old: 2000, new: 3000 }))).toBe('Slower');
    expect(changeWord(measure({ unit: 'ms', old: 3000, new: 2000 }))).toBe('Faster');
    expect(changeWord(measure({ unit: 'percent', old: 3, new: 5.1 }))).toBe('Higher');
    expect(changeWord(measure({ unit: 'score', old: 0.1, new: 0.05 }))).toBe('Lower');
    expect(changeWord(measure({ unit: 'percent', old: 3, new: 3 }))).toBe('No change');
  });
});

describe('ReleasesTab', () => {
  it('writes each figure with its unit and says Held for review only where the gate holds it', () => {
    render(
      <ReleasesTab
        compare={{ old: '1.4.2', new: '1.4.3' }}
        measures={[
          measure({}),
          measure({ measure: 'Errors shown per 100 page views', old: 1, new: 1, review: false }),
          measure({ measure: 'Largest contentful paint, p75', unit: 'ms', old: 2000, new: 2500, review: false }),
        ]}
        pipeline={[]}
      />,
    );

    const friction = screen.getByRole('row', { name: /Friction events/ });
    expect(friction).toHaveTextContent('3%');
    expect(friction).toHaveTextContent('5.1%');
    expect(friction).toHaveTextContent('Held for review');
    expect(screen.getByRole('row', { name: /Errors shown/ })).not.toHaveTextContent('Held for review');
    expect(screen.getByRole('row', { name: /Largest contentful paint/ })).toHaveTextContent('2500 ms');
  });

  it('says what is needed when there is no comparison, and still lists the pipeline', () => {
    render(
      <ReleasesTab
        compare={null}
        measures={[]}
        pipeline={[{ name: 'messages.outbound', active: 3, deadLettered: 1, oldestSeconds: 95 }]}
      />,
    );

    expect(screen.getByText('Two releases with at least 10 sessions each are needed to compare.')).toBeInTheDocument();
    const pipeline = screen.getByRole('table', { name: /pipeline health/i });
    expect(within(pipeline).getByRole('row', { name: /messages\.outbound/ })).toHaveTextContent('1');
  });

  it('names the two releases as the columns of the comparison', () => {
    render(<ReleasesTab compare={{ old: '1.4.1', new: '1.4.2' }} measures={[measure({})]} pipeline={[]} />);

    const measures = screen.getByRole('table', { name: /release comparison/i });
    expect(within(measures).getByRole('columnheader', { name: '1.4.1' })).toBeInTheDocument();
    expect(within(measures).getByRole('columnheader', { name: '1.4.2' })).toBeInTheDocument();
  });

  it('shows n/a for a queue with no oldest message, and marks a dead-lettered queue with a shape', () => {
    render(
      <ReleasesTab
        compare={null}
        measures={[]}
        pipeline={[
          { name: 'messages.outbound', active: 2, deadLettered: 0, oldestSeconds: null },
          { name: 'booking.events', active: 0, deadLettered: 1, oldestSeconds: 4 },
        ]}
      />,
    );

    const pipeline = screen.getByRole('table', { name: /pipeline health/i });
    expect(within(pipeline).getByRole('row', { name: /messages\.outbound/ })).toHaveTextContent('n/a');
    const dead = within(pipeline).getByRole('row', { name: /booking\.events/ });
    expect(dead.querySelector('[aria-hidden="true"]')).not.toBeNull();
    expect(within(pipeline).getByRole('row', { name: /messages\.outbound/ }).querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(
      <ReleasesTab compare={{ old: '1.4.2', new: '1.4.3' }} measures={[measure({})]} pipeline={[]} />,
    );

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
