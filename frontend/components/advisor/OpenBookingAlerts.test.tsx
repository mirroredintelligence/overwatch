import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { runAxe } from '@/test/a11y';
import { STATE_NOT_REACHED, STATE_WITHDRAWN } from '@/test/fixtures/bookings';
import { openAlerts, resetBookingRequests, seenAlertReads } from '@/test/msw/handlers/bookings';
import { server } from '@/test/msw/server';
import { OpenBookingAlerts } from './OpenBookingAlerts';

// The advisor who is not looking at a booking card still sees a withdrawal nobody has answered (H-496,
// DEC-854): a strip on every advisor page, read from the back end's open alerts. It answers nothing: the
// answer is given on the card, where the caller's case is.

function settle(check: () => void) {
  return waitFor(check, { timeout: 2000 });
}

beforeEach(() => {
  resetBookingRequests();
});

describe('OpenBookingAlerts', () => {
  it('shows nothing when no alert is open, and is not in the page', async () => {
    const { container } = render(<OpenBookingAlerts pollMs={60_000} />);
    await settle(() => expect(seenAlertReads.count).toBe(1));
    expect(container).toBeEmptyDOMElement();
  });

  it('names a withdrawal nobody has answered, with the way to its case', async () => {
    openAlerts.current = [STATE_WITHDRAWN];
    const { container } = render(<OpenBookingAlerts pollMs={60_000} />);
    expect(await screen.findByText(/A service withdrew booking 4821/)).toBeInTheDocument();
    expect(screen.getByText(/Phone the caller, then answer the alert/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open case case-1001' })).toHaveAttribute('href', '/advisor/case/case-1001/options');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('names a not-reached report in its own words', async () => {
    openAlerts.current = [STATE_NOT_REACHED];
    render(<OpenBookingAlerts pollMs={60_000} />);
    expect(await screen.findByText(/A service could not reach the patient for booking 4821/)).toBeInTheDocument();
  });

  it('lists each open alert, and says how many', async () => {
    openAlerts.current = [STATE_WITHDRAWN, { ...STATE_NOT_REACHED, id: 'bk-9', reference: '4830', caseRef: 'case-2002' }];
    render(<OpenBookingAlerts pollMs={60_000} />);
    expect(await screen.findByRole('heading', { name: '2 booking alerts to answer' })).toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(2);
  });

  it('shows the alert as a live region the advisor is told of, once it appears', async () => {
    openAlerts.current = [STATE_WITHDRAWN];
    render(<OpenBookingAlerts pollMs={60_000} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('booking 4821');
  });

  it('reads again at its interval and drops an alert that has been answered', async () => {
    openAlerts.current = [STATE_WITHDRAWN];
    render(<OpenBookingAlerts pollMs={40} />);
    await screen.findByText(/booking 4821/);
    openAlerts.current = [];
    await settle(() => expect(screen.queryByText(/booking 4821/)).toBeNull());
    expect(seenAlertReads.count).toBeGreaterThan(1);
  });

  it('says it could not check, when the read fails, rather than showing nothing as if all were answered', async () => {
    server.use(http.get('/api/bff/bookings', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<OpenBookingAlerts pollMs={60_000} />);
    expect(await screen.findByRole('status')).toHaveTextContent('We could not check for booking alerts.');
  });

  it('keeps the alerts it had when a later read fails', async () => {
    openAlerts.current = [STATE_WITHDRAWN];
    render(<OpenBookingAlerts pollMs={40} />);
    await screen.findByText(/booking 4821/);
    server.use(http.get('/api/bff/bookings', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    await screen.findByText('We could not check for booking alerts.');
    expect(screen.getByText(/booking 4821/)).toBeInTheDocument();
  });

  it('shows no personal detail: a reference, a case and no patient', async () => {
    openAlerts.current = [STATE_WITHDRAWN];
    const { container } = render(<OpenBookingAlerts pollMs={60_000} />);
    await screen.findByText(/booking 4821/);
    expect(container.textContent).not.toMatch(/Sample Patient|DT4|07700/);
  });
});
