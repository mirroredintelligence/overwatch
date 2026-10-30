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

  it('passes vitest-axe', async () => {
    const { container } = render(<Waterfall totalMs={2400} spans={SPANS} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
