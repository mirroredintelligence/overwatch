import { render, screen, waitFor } from '@testing-library/react';
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
  it('shows the escalation line with the deputy and the time it falls due', () => {
    render(<AlertDetail alert={alert} />);
    expect(screen.getByText('If nobody acknowledges by 14:19, your deputy is alerted.')).toBeInTheDocument();
    expect(screen.getByText('Acknowledging tells others it is being handled.')).toBeInTheDocument();
  });

  it('snoozes the escalation for one hour and says when it now falls due', async () => {
    server.use(http.post('/api/bff/exec/alerts/:id/snooze', () =>
      HttpResponse.json({ alertId: 'al-1', escalatesAt: '2026-10-23T14:19:00Z' })));
    render(<AlertDetail alert={alert} />);
    await userEvent.click(screen.getByRole('button', { name: 'Snooze for 1 hour' }));
    await waitFor(() => expect(screen.getByText('If nobody acknowledges by 15:19, your deputy is alerted.')).toBeInTheDocument());
  });

  it('acknowledges and shows the state, and offers the way back to the list', async () => {
    server.use(http.post('/api/bff/exec/alerts/:id/acknowledge', () => HttpResponse.json({ id: 'al-1', status: 'completed' })));
    render(<AlertDetail alert={alert} />);
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(await screen.findByText('Acknowledged.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to alerts' })).toHaveAttribute('href', '/planning/alerts');
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

  it('has no accessibility violations', async () => {
    const { container } = render(<AlertDetail alert={alert} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
