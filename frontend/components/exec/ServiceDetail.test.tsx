import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { BoardEntry } from '@/lib/board/types';
import { NOW } from '@/test/fixtures/board';
import { runAxe } from '@/test/a11y';
import type { AlertItem } from '@/lib/exec/alerts';
import { ServiceAlertCard, ServiceDetail, alertRowText } from './ServiceDetail';

const entry: BoardEntry = {
  serviceId: 'svc-hah', name: 'Hospital at home', category: 'hospital-at-home-or-virtual-ward', status: 'over-capacity',
  effectiveAvailable: null, overBy: 4, used: 16, established: 12, pending: 0, unitLabel: 'virtual beds',
  comment: null, reportedAt: '2026-10-23T13:01:00Z', nextDueAt: null, wasDueAt: null,
};

const newAlert: AlertItem = {
  id: 'al-1', kind: 'over-capacity', serviceId: 'svc-hah', serviceName: 'Hospital at home', detail: '+4',
  raisedAt: '2026-10-23T13:12:00Z', state: 'new', escalatesAt: null, escalatesTo: null, acknowledgedAt: null,
};

describe('ServiceDetail', () => {
  it('shows the status as shape and word, the service kind, and when it was last updated', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Hospital at home' })).toBeInTheDocument();
    const tag = screen.getByText('Over capacity').closest('[data-variant]');
    expect(tag).toHaveAttribute('data-variant', 'over');
    expect(tag?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('Virtual beds · updated 11 min ago')).toBeInTheDocument();
  });

  it('shows the figure over established capacity', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByText('+4')).toBeInTheDocument();
    expect(screen.getByText('over established capacity')).toBeInTheDocument();
  });

  it('says the number of virtual beds used when the service is over established capacity by count', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByText('16 of 12 virtual beds')).toBeInTheDocument();
  });

  it('shows what is free when the service is not over capacity', () => {
    render(<ServiceDetail entry={{ ...entry, status: 'accepting', overBy: null, effectiveAvailable: 3, used: 7, established: 10 }} now={NOW.toISOString()} />);
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('virtual beds free')).toBeInTheDocument();
  });

  it('draws the day as a strip with the time of the last report and now, and names no interval it does not hold', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    const today = screen.getByRole('group', { name: 'Today' });
    const strip = within(today).getByRole('img');
    expect(strip).toHaveAccessibleName('Last reported at 14:01, now 14:12');
    expect(within(today).getByText('00:00')).toBeInTheDocument();
    expect(within(today).getByText('Last reported 14:01')).toBeInTheDocument();
    expect(within(today).getByText('now 14:12')).toBeInTheDocument();
    expect(within(today).getByText('24:00')).toBeInTheDocument();
  });

  it('draws no strip when nothing has been reported, and says so', () => {
    render(<ServiceDetail entry={{ ...entry, reportedAt: null }} now={NOW.toISOString()} />);
    expect(screen.queryByRole('group', { name: 'Today' })).not.toBeInTheDocument();
    expect(screen.getByText('Virtual beds · no report yet')).toBeInTheDocument();
  });

  it('draws no strip for a report of another day', () => {
    render(<ServiceDetail entry={{ ...entry, reportedAt: '2026-10-22T13:01:00Z' }} now={NOW.toISOString()} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
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
    const alert: AlertItem = { ...newAlert, state: 'acknowledged', acknowledgedAt: '2026-10-23T13:40:00Z' };
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
    const base: AlertItem = { ...newAlert, id: 'al-2', serviceName: null, detail: null };
    expect(alertRowText(base)).toBe('New, alerted 14:12');
    expect(alertRowText({ ...base, state: 'escalated' })).toBe('Escalated, alerted 14:12');
    expect(alertRowText({ ...base, state: 'closed' })).toBe('Closed, alerted 14:12');
  });

  it('links back to the alerts', () => {
    render(<ServiceDetail entry={entry} now={NOW.toISOString()} />);
    expect(screen.getByRole('link', { name: 'Back to alerts' })).toHaveAttribute('href', '/planning/alerts');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ServiceDetail entry={entry} now={NOW.toISOString()} coordinationPhone="01632 960001" alert={newAlert} escalationInPlace />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('ServiceAlertCard', () => {
  it('shows the alert for the service and the one way into it', () => {
    render(<ServiceAlertCard alert={newAlert} />);
    const card = screen.getByRole('region', { name: 'Alert for this service' });
    expect(within(card).getByText('Hospital at home over capacity')).toBeInTheDocument();
    expect(within(card).getByText('New, alerted 14:12')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'Open the alert' })).toHaveAttribute('href', '/planning/alerts/al-1');
  });

  it('says there is no alert, with nothing to open', () => {
    render(<ServiceAlertCard alert={null} />);
    expect(screen.getByText('No alert for this service')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open the alert' })).not.toBeInTheDocument();
  });

  it('says the alerts could not be read, and makes up no row, when they were not read', () => {
    render(<ServiceAlertCard alert={undefined} />);
    expect(screen.getByText('The alerts could not be read.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open the alert' })).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ServiceAlertCard alert={newAlert} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
