import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { BoardEntry } from '@/lib/board/types';
import { NOW } from '@/test/fixtures/board';
import { runAxe } from '@/test/a11y';
import type { AlertItem } from '@/lib/exec/alerts';
import { ServiceDetail, alertRowText } from './ServiceDetail';

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

  it('offers a call to the duty coordinator when the board holds the number, and nothing when it holds none', () => {
    const { unmount } = render(<ServiceDetail entry={entry} now={NOW.toISOString()} coordinationPhone="01632 960001" />);
    const call = screen.getByRole('link', { name: 'Call the duty coordinator' });
    expect(call).toHaveAttribute('href', 'tel:01632960001');
    expect(screen.getByText('01632 960001')).toBeInTheDocument();
    unmount();
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} coordinationPhone={null} />);
    expect(screen.queryByRole('link', { name: 'Call the duty coordinator' })).not.toBeInTheDocument();
  });

  it('shows the alert row and the escalation row when they were read, and neither when they were not', () => {
    const alert: AlertItem = {
      id: 'al-1', kind: 'over-capacity', serviceId: 'svc-hah', serviceName: 'Hospital at home', detail: '+4',
      raisedAt: '2026-10-23T13:12:00Z', state: 'acknowledged', escalatesAt: null, escalatesTo: null, acknowledgedAt: '2026-10-23T13:40:00Z',
    };
    const { unmount } = render(<ServiceDetail entry={entry} now={NOW.toISOString()} alert={alert} escalationInPlace />);
    const facts = screen.getByText('Alert').closest('dl')!;
    expect(facts).toHaveTextContent('AlertAcknowledged by you 14:40');
    expect(facts).toHaveTextContent('Escalation in placeYes');
    unmount();
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.queryByText('Escalation in place')).not.toBeInTheDocument();
  });

  it('says what became of the alert in words', () => {
    expect(alertRowText(null)).toBe('No alert for this service');
    const base: AlertItem = {
      id: 'al-2', kind: 'over-capacity', serviceId: 'svc-hah', serviceName: null, detail: null,
      raisedAt: '2026-10-23T13:12:00Z', state: 'new', escalatesAt: null, escalatesTo: null, acknowledgedAt: null,
    };
    expect(alertRowText(base)).toBe('New, alerted 14:12');
    expect(alertRowText({ ...base, state: 'escalated' })).toBe('Escalated, alerted 14:12');
    expect(alertRowText({ ...base, state: 'closed' })).toBe('Closed, alerted 14:12');
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
