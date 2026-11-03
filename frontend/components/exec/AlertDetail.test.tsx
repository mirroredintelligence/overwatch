import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import type { AlertItem } from '@/lib/exec/alerts';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AlertDetail } from './AlertDetail';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const alert: AlertItem = {
  id: 'al-1', kind: 'over-capacity', serviceId: 'svc-hah', serviceName: 'Hospital at home', detail: '+4',
  raisedAt: '2026-10-23T13:04:00Z', state: 'new', escalatesAt: '2026-10-23T13:19:00Z', escalatesTo: 'deputy', acknowledgedAt: null,
};

describe('AlertDetail', () => {
  it('is a card named for the alert, with the kind above the service name and a status tag in words', () => {
    render(<AlertDetail alert={alert} />);
    const card = screen.getByRole('region', { name: 'Hospital at home over capacity' });
    expect(within(card).getByText('Alert · over capacity')).toBeInTheDocument();
    expect(within(card).getByRole('heading', { level: 2, name: 'Hospital at home' })).toBeInTheDocument();
    expect(within(card).getByText('New')).toBeInTheDocument();
    expect(within(card).getByText('+4 over established capacity. Alerted 14:04.')).toBeInTheDocument();
  });

  it('shows the escalation line with the deputy and the time it falls due', () => {
    render(<AlertDetail alert={alert} />);
    expect(screen.getByText('If nobody acknowledges by 14:19, your deputy is alerted.')).toBeInTheDocument();
    expect(screen.getByText('Acknowledging tells others it is being handled. It does not change the board.')).toBeInTheDocument();
  });

  it('keeps Acknowledge, Call and Snooze in that order', () => {
    render(<AlertDetail alert={alert} coordinationPhone="01632 960001" />);
    const all = Array.from(document.querySelectorAll('button, a')).map((node) => node.textContent);
    expect(all.slice(0, 3)).toEqual(['Acknowledge', 'Call the duty coordinator', 'Snooze for 1 hour']);
  });

  it('snoozes the escalation for one hour and says when it now falls due', async () => {
    server.use(http.post('/api/bff/exec/alerts/:id/snooze', () =>
      HttpResponse.json({ alertId: 'al-1', escalatesAt: '2026-10-23T14:19:00Z' })));
    render(<AlertDetail alert={alert} />);
    await userEvent.click(screen.getByRole('button', { name: 'Snooze for 1 hour' }));
    await waitFor(() => expect(screen.getByText('If nobody acknowledges by 15:19, your deputy is alerted.')).toBeInTheDocument());
  });

  it('acknowledges in place, shows the state, tells the page, and offers the way back to the list', async () => {
    const onAcknowledged = vi.fn();
    server.use(http.post('/api/bff/exec/alerts/:id/acknowledge', () => HttpResponse.json({ id: 'al-1', status: 'completed' })));
    render(<AlertDetail alert={alert} onAcknowledged={onAcknowledged} />);
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(await screen.findByText('Acknowledged.')).toBeInTheDocument();
    expect(onAcknowledged).toHaveBeenCalledWith('al-1');
    expect(screen.getByRole('link', { name: 'Back to alerts' })).toHaveAttribute('href', '/planning/alerts');
  });

  it('says so and keeps the buttons when the acknowledgement fails', async () => {
    server.use(http.post('/api/bff/exec/alerts/:id/acknowledge', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    render(<AlertDetail alert={alert} />);
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(await screen.findByText('Could not acknowledge. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeEnabled();
  });

  it('offers a call to the duty coordinator when the board holds the number', () => {
    render(<AlertDetail alert={alert} coordinationPhone="01632 960001" />);
    expect(screen.getByRole('link', { name: 'Call the duty coordinator' })).toHaveAttribute('href', 'tel:01632960001');
  });

  it('shows an alert acknowledged earlier as acknowledged, with the time, and offers no second acknowledgement', () => {
    render(<AlertDetail alert={{ ...alert, state: 'acknowledged', acknowledgedAt: '2026-10-23T12:40:00Z', escalatesAt: null, escalatesTo: null }} />);
    expect(screen.getByText('Acknowledged at 13:40')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Snooze for 1 hour' })).not.toBeInTheDocument();
  });

  describe('as the pane beside the list', () => {
    it('lays out what happens if nobody acts, from the alert and its escalation time', () => {
      render(<AlertDetail alert={alert} layout="pane" />);
      expect(screen.getByText('What happens if nobody acts')).toBeInTheDocument();
      expect(screen.getByText('You are alerted now (14:04)')).toBeInTheDocument();
      expect(screen.getByText('Your deputy is alerted at 14:19 if you have not acknowledged')).toBeInTheDocument();
    });

    it('names no second step when the alert holds no escalation time', () => {
      render(<AlertDetail alert={{ ...alert, escalatesAt: null, escalatesTo: null }} layout="pane" />);
      expect(screen.queryByText(/Your deputy is alerted at/)).not.toBeInTheDocument();
    });

    it('offers Open the service, and no Back to alerts', () => {
      render(<AlertDetail alert={alert} layout="pane" coordinationPhone="01632 960001" />);
      expect(screen.getByRole('link', { name: 'Open the service' })).toHaveAttribute('href', '/planning/services/svc-hah');
      expect(screen.queryByRole('link', { name: 'Back to alerts' })).not.toBeInTheDocument();
    });

    it('offers no way into a service when the alert has none', () => {
      render(<AlertDetail alert={{ ...alert, serviceId: null, serviceName: null }} layout="pane" />);
      expect(screen.queryByRole('link', { name: 'Open the service' })).not.toBeInTheDocument();
    });
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<AlertDetail alert={alert} coordinationPhone="01632 960001" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no accessibility violations as the pane', async () => {
    const { container } = render(<AlertDetail alert={alert} layout="pane" coordinationPhone="01632 960001" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
