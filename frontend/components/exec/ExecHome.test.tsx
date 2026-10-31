import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Board, BoardEntry } from '@/lib/board/types';
import { runAxe } from '@/test/a11y';
import { ExecHome } from './ExecHome';

const base: BoardEntry = {
  serviceId: 's', name: 'S', category: 'urgent-community-response', status: 'accepting',
  effectiveAvailable: 4, overBy: null, used: 4, established: 8, pending: 0, unitLabel: 'referrals',
  comment: null, reportedAt: '2026-10-23T13:03:00Z', nextDueAt: null, wasDueAt: null,
};

const sample: Board = {
  pressure: 'watch',
  allLimitedOrWorse: false,
  generatedAt: '2026-10-23T13:12:00Z',
  organisation: 'Dorset',
  entries: [
    { ...base, serviceId: 'a', name: 'Hospital at home', status: 'over-capacity', overBy: 4, reportedAt: '2026-10-23T12:10:00Z' },
    { ...base, serviceId: 'b', name: 'UCR East', status: 'limited' },
    { ...base, serviceId: 'c', name: 'Virtual ward', status: 'not-accepting', reportedAt: '2026-10-23T11:50:00Z' },
    { ...base, serviceId: 'd', name: 'UCR West', status: 'not-updated', reportedAt: '2026-10-23T09:02:00Z' },
    { ...base, serviceId: 'e', name: 'Community beds', status: 'accepting' },
    { ...base, serviceId: 'f', name: 'Night service', status: 'out-of-hours' },
  ],
};

describe('ExecHome', () => {
  it('shows the system name, the pressure word and the count of services limited or worse', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Dorset' })).toBeInTheDocument();
    expect(screen.getByText('Watch')).toBeInTheDocument();
    expect(screen.getByText('3 of 5 services limited or worse')).toBeInTheDocument();
  });

  it('lists what needs attention, one line each', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    const list = screen.getByRole('list', { name: 'Needs attention (3)' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(within(list).getByText('Over capacity +4, reported 13:10')).toBeInTheDocument();
    expect(within(list).getByText('Not updated for 4 hrs 10 min')).toBeInTheDocument();
  });

  it('links to all services', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    expect(screen.getByRole('link', { name: 'See all services' })).toHaveAttribute('href', '/planning/services');
  });

  it('links to the planning flows (W51)', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    expect(screen.getByRole('link', { name: 'See planning flows' })).toHaveAttribute('href', '/planning/flows');
  });

  it('links an executive to the alerts on their phone, and a lead, who has no phone app, to nothing of the kind (W9H)', () => {
    const { rerender } = render(<ExecHome board={sample} name="Dorset" phoneAlerts />);
    expect(screen.getByRole('link', { name: 'Alerts on this phone' })).toHaveAttribute('href', '/planning/phone');
    rerender(<ExecHome board={sample} name="Dorset" />);
    expect(screen.queryByRole('link', { name: 'Alerts on this phone' })).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ExecHome board={sample} name="Dorset" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
