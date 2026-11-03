import Link from 'next/link';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Waterfall } from './Waterfall';

const SPANS = [
  { spanId: 'root', parentSpanId: null, name: 'POST /api/bff/bookings', offsetMs: 0, durationMs: 2400, status: 'ok' },
  { spanId: 'cypher', parentSpanId: 'root', name: 'Cypher BookingRequest', offsetMs: 600, durationMs: 1200, status: 'ok' },
];

describe('Waterfall', () => {
  it('positions a 1.2 s span starting at 0.6 s at 25% left and 50% width of a 2.4 s trace', () => {
    const { container } = render(<Waterfall totalMs={2400} spans={SPANS} />);

    const bar = container.querySelector('[data-span="cypher"]') as HTMLElement;
    expect(bar.style.left).toBe('25%');
    expect(bar.style.width).toBe('50%');
  });

  it('has a text table of the same spans, so the bars are not the only form of the timing', () => {
    render(<Waterfall totalMs={2400} spans={SPANS} />);

    const table = screen.getByRole('table', { name: /spans/i });
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(SPANS.length + 1);
    expect(within(table).getByText('Cypher BookingRequest')).toBeInTheDocument();
    expect(within(table).getByText('1.2 s')).toBeInTheDocument();
  });

  it('hatches the slowest child span, and names it in words with its time and the budget', () => {
    const { container } = render(<Waterfall totalMs={2400} spans={SPANS} />);

    expect((container.querySelector('[data-span="cypher"]') as HTMLElement).dataset.slowest).toBe('true');
    expect((container.querySelector('[data-span="root"]') as HTMLElement).dataset.slowest).toBe('false');
    expect(screen.getByText(/Cypher BookingRequest took 1\.2 s\. The budget for this query is 200 ms\./)).toBeInTheDocument();
  });

  it('gives the chart an accessible name that states the finding', () => {
    render(<Waterfall totalMs={2400} spans={SPANS} />);

    expect(screen.getByRole('img', { name: /slowest step is Cypher BookingRequest, 1\.2 s, of 2\.4 s/i })).toBeInTheDocument();
  });

  it('shows the actions it is given beside the chart', () => {
    render(<Waterfall totalMs={2400} spans={SPANS} actions={<Link href="/console/session/s-1">Back to the session</Link>} />);

    expect(screen.getByRole('link', { name: 'Back to the session' })).toHaveAttribute('href', '/console/session/s-1');
  });

  it('says so when a trace has no spans', () => {
    render(<Waterfall totalMs={0} spans={[]} />);

    expect(screen.getByText('No spans were recorded for this trace.')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<Waterfall totalMs={2400} spans={SPANS} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
