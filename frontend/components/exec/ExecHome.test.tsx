import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Board, BoardEntry } from '@/lib/board/types';
import type { WeekSummary } from '@/lib/exec/weekSummary';
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

  it('links to where coverage runs out', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    expect(screen.getByRole('link', { name: 'Where coverage runs out' })).toHaveAttribute('href', '/planning/coverage');
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

  it('sits on the planning stage at its home state', () => {
    const { container } = render(<ExecHome board={sample} name="Dorset" />);
    expect(container.querySelector('[data-planning-stage]')).toHaveAttribute('data-planning-stage', 'home');
  });

  it('counts the services in five tiles, each a number and a word', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    const group = screen.getByRole('group', { name: 'Services by state' });
    const tiles = within(group).getAllByRole('listitem');
    expect(tiles).toHaveLength(5);
    expect(within(tiles[0]).getByText('1')).toBeInTheDocument();
    expect(within(tiles[0]).getByText(/Accepting/)).toBeInTheDocument();
    expect(within(tiles[3]).getByText(/Over capacity/)).toBeInTheDocument();
    expect(within(tiles[4]).getByText(/Not updated/)).toBeInTheDocument();
  });

  it('gives each service that needs attention a status in words and an Open link that names the service', () => {
    render(<ExecHome board={sample} name="Dorset" />);
    const list = screen.getByRole('list', { name: 'Needs attention (3)' });
    expect(within(list).getByText('Over capacity')).toBeInTheDocument();
    expect(within(list).getByText('Not accepting')).toBeInTheDocument();
    expect(within(list).getByText('Not updated')).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: 'Open Hospital at home' })).toHaveAttribute('href', '/planning/services/a');
    expect(within(list).getByRole('link', { name: 'Open Virtual ward' })).toHaveAttribute('href', '/planning/services/c');
  });

  it('says why the list is empty when nothing needs attention, never a blank', () => {
    const calm: Board = { ...sample, pressure: 'normal', entries: [sample.entries[4]!, sample.entries[1]!] };
    render(<ExecHome board={calm} name="Dorset" />);
    expect(screen.getByText('Nothing needs attention')).toBeInTheDocument();
    expect(screen.getByText(/All 2 services/)).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Needs attention (0)' })).not.toBeInTheDocument();
  });

  describe('the week glance', () => {
    const week: WeekSummary = {
      from: '2026-10-17',
      to: '2026-10-23',
      referrals: { value: 640, suppressed: false },
      bestFitUnavailablePct: { value: 4, suppressed: false },
      onTimePct: { value: 92, suppressed: false },
      medianMinutesToConfirmed: { value: 9, suppressed: false },
      updates: { value: 1200, suppressed: false },
      minutesPerCall: null,
      timeBackText: null,
    };

    it('shows the week, the referrals and the updates on time, and the way to the week', () => {
      render(<ExecHome board={sample} name="Dorset" week={week} />);
      const glance = screen.getByRole('region', { name: 'This week' });
      expect(within(glance).getByText('17 to 23 Oct')).toBeInTheDocument();
      expect(within(glance).getByText('640')).toBeInTheDocument();
      expect(within(glance).getByText('referrals')).toBeInTheDocument();
      expect(within(glance).getByText('92%')).toBeInTheDocument();
      expect(within(glance).getByText('updates on time')).toBeInTheDocument();
      expect(within(glance).getByRole('link', { name: 'See the week' })).toHaveAttribute('href', '/planning/week');
    });

    it('never shows a withheld figure as a number', () => {
      render(<ExecHome board={sample} name="Dorset" week={{ ...week, referrals: { value: null, suppressed: true } }} />);
      expect(within(screen.getByRole('region', { name: 'This week' })).getByText('fewer than 10')).toBeInTheDocument();
    });

    it('says so when the week could not be read, and still offers the way to it', () => {
      render(<ExecHome board={sample} name="Dorset" week={null} />);
      const glance = screen.getByRole('region', { name: 'This week' });
      expect(within(glance).getByText('The figures for the week could not be read.')).toBeInTheDocument();
      expect(within(glance).getByRole('link', { name: 'See the week' })).toBeInTheDocument();
    });
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ExecHome board={sample} name="Dorset" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
