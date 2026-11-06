import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { DayChart } from './DayChart';

// The day chart (DEC-1343): drawn from the service's reports, broken where the capacity was unknown, with the same
// figures in a table, and nothing drawn when it cannot be read.

describe('DayChart', () => {
  it('draws the chart with the unknown stretch named in words, and the reports in a table', async () => {
    render(<DayChart serviceId="svc-1" />);
    const chart = await screen.findByRole('img');
    expect(chart).toHaveAttribute('aria-label', expect.stringContaining('1 report in the last day.'));
    expect(chart).toHaveAttribute('aria-label', expect.stringContaining('Capacity unknown'));
    expect(screen.getByText('Capacity unknown')).toBeInTheDocument();
    const table = screen.getByRole('table', { hidden: true });
    expect(within(table).getByText('4')).toBeInTheDocument();
  });

  it('says so and draws nothing when the day cannot be read', async () => {
    server.use(http.get('/api/bff/advisor/services/:id/history', () => HttpResponse.json({}, { status: 503 })));
    render(<DayChart serviceId="svc-1" />);
    await waitFor(() => expect(screen.getByText('The day could not be read. Nothing is drawn.')).toBeInTheDocument());
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('says so when the answer is not the shape it knows', async () => {
    server.use(http.get('/api/bff/advisor/services/:id/history', () => HttpResponse.json({ points: 'no' })));
    render(<DayChart serviceId="svc-1" />);
    await waitFor(() => expect(screen.getByText('The day could not be read. Nothing is drawn.')).toBeInTheDocument());
  });

  it('has no axe violations', async () => {
    const { container } = render(<DayChart serviceId="svc-1" />);
    await screen.findByRole('img');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
