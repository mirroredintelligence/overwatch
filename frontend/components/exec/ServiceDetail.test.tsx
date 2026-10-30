import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { BoardEntry } from '@/lib/board/types';
import { NOW } from '@/test/fixtures/board';
import { runAxe } from '@/test/a11y';
import { ServiceDetail } from './ServiceDetail';

const entry: BoardEntry = {
  serviceId: 'svc-hah', name: 'Hospital at home', category: 'hospital-at-home-or-virtual-ward', status: 'over-capacity',
  effectiveAvailable: null, overBy: 4, used: 16, established: 12, pending: 0, unitLabel: 'virtual beds',
  comment: null, reportedAt: '2026-10-23T13:01:00Z', nextDueAt: null, wasDueAt: null,
};

describe('ServiceDetail', () => {
  it('shows the status, when it was last updated and the figure over established capacity', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Hospital at home' })).toBeInTheDocument();
    expect(screen.getByText('Over capacity')).toBeInTheDocument();
    expect(screen.getByText('Updated 11 min ago')).toBeInTheDocument();
    expect(screen.getByText('+4')).toBeInTheDocument();
    expect(screen.getByText('over established capacity')).toBeInTheDocument();
  });

  it('says the number of virtual beds used when the service is over established capacity by count', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByText('16 of 12 virtual beds')).toBeInTheDocument();
  });

  it('links back to the alerts', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByRole('link', { name: 'Back to alerts' })).toHaveAttribute('href', '/planning/alerts');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
