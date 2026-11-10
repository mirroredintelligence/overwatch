import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { ServiceActions } from './ServiceActions';
import { ServiceCheck } from './ServiceCheck';
import { WorkspaceProvider } from './WorkspaceProvider';

// "Book a slot" on the service page (DEC-1377): the triage card, then the answer for this one service, with no
// navigation. The back end decides the fit; these tests only show what is done with its answer. Neutral words only.

const POSTCODE = 'DT4 8XX';
const FITS = { serviceId: 'svc-a', fits: true, reasons: [], fitsNeeds: ['frailty'], warnings: ['Its figure is old.'], phone: '01305 000000' };
const NOT_FIT = { serviceId: 'svc-a', fits: false, reasons: ['Does not accept frailty'], fitsNeeds: [], warnings: [], phone: '01305 000000' };

let posted: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  posted = [];
  window.localStorage.clear();
  window.sessionStorage.clear();
  server.use(
    http.get('/api/bff/advisor/postcodes', () => HttpResponse.json({ postcodes: [POSTCODE] })),
    http.get('/api/bff/advisor/postcodes/locate', () => HttpResponse.json({ status: 'found', lat: 50.6, lon: -2.4 })),
  );
});

function serveCheck(answer: unknown, status = 200) {
  server.use(
    http.post('/api/bff/advisor-v2/services/svc-a/check', async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(answer as Record<string, unknown>, { status });
    }),
  );
}

function renderCheck(onClose = vi.fn()) {
  render(
    <WorkspaceProvider role="advisor">
      <ServiceCheck serviceId="svc-a" onClose={onClose} />
    </WorkspaceProvider>,
  );
  return onClose;
}

async function fillCard(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: '80+' }));
  await user.type(screen.getByLabelText('Postcode'), 'DT4');
  await user.click(await screen.findByRole('option', { name: POSTCODE }));
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await user.click(screen.getByRole('button', { name: 'Frailty' }));
  await user.click(screen.getByRole('button', { name: 'Today' }));
}

describe('ServiceCheck', () => {
  it('asks the age and the postcode first, with no check yet', () => {
    renderCheck();
    expect(screen.getByRole('heading', { name: 'Step 1 of 2 · Age and postcode' })).toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it('checks by itself once the criteria are complete, and says the patient fits, with the phone and the caveat', async () => {
    serveCheck(FITS);
    const user = userEvent.setup();
    renderCheck();
    await fillCard(user);
    expect(await screen.findByRole('heading', { name: 'This patient fits this service' })).toBeInTheDocument();
    expect(posted).toEqual([{ postcode: POSTCODE, ageBand: '80+', needs: ['frailty'], urgency: 'today' }]);
    expect(screen.getByText('Takes: frailty.')).toBeInTheDocument();
    expect(screen.getByText('Phone: 01305 000000')).toBeInTheDocument();
    expect(screen.getByText('Its figure is old.')).toBeInTheDocument();
    expect(screen.getByText(/Phone the service to book/)).toBeInTheDocument();
    expect(screen.getByText(/The receiving service confirms/)).toBeInTheDocument();
  });

  it('says the patient does not fit, and why, and offers no booking', async () => {
    serveCheck(NOT_FIT);
    const user = userEvent.setup();
    renderCheck();
    await fillCard(user);
    expect(await screen.findByRole('heading', { name: 'This patient does not fit this service' })).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Reasons' })).getByText('Does not accept frailty')).toBeInTheDocument();
    expect(screen.queryByText(/Phone the service to book/)).toBeNull();
  });

  it('says so when the check fails, and never shows a fit', async () => {
    serveCheck({ code: 'exception' }, 502);
    const user = userEvent.setup();
    renderCheck();
    await fillCard(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('The check could not be made');
    expect(screen.queryByText(/fits this service/)).toBeNull();
  });

  it('checks another patient from the start, and closes', async () => {
    serveCheck(FITS);
    const user = userEvent.setup();
    const onClose = renderCheck();
    await fillCard(user);
    await user.click(await screen.findByRole('button', { name: 'Check another patient' }));
    expect(screen.getByRole('heading', { name: 'Step 1 of 2 · Age and postcode' })).toBeInTheDocument();
    expect(screen.getByLabelText('Postcode')).toHaveValue('');
    await fillCard(user);
    await user.click(await screen.findByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(posted).toHaveLength(2);
  });

  it('keeps the criteria out of the address, the browser storage and the page', async () => {
    serveCheck(FITS);
    const user = userEvent.setup();
    renderCheck();
    await fillCard(user);
    await screen.findByRole('heading', { name: 'This patient fits this service' });
    expect(window.location.href).not.toMatch(/DT4|80|frailty/i);
    expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toMatch(/DT4|frailty/i);
  });

  it('has no accessibility violations on the answer', async () => {
    serveCheck(FITS);
    const user = userEvent.setup();
    const { container } = render(
      <WorkspaceProvider role="advisor">
        <ServiceCheck serviceId="svc-a" onClose={() => undefined} />
      </WorkspaceProvider>,
    );
    await fillCard(user);
    await screen.findByRole('heading', { name: 'This patient fits this service' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('ServiceActions', () => {
  function serveAsk(status: number) {
    const keys: (string | null)[] = [];
    server.use(
      http.post('/api/bff/advisor-v2/services/svc-a/ask', ({ request }) => {
        keys.push(request.headers.get('idempotency-key'));
        return status === 200 ? HttpResponse.json({ queued: true }) : HttpResponse.json({ code: 'conflict' }, { status });
      }),
    );
    return keys;
  }

  it('"Book a slot" calls the handler and does nothing else', async () => {
    const onCheck = vi.fn();
    render(<ServiceActions serviceId="svc-a" onCheck={onCheck} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Book a slot' }));
    expect(onCheck).toHaveBeenCalledTimes(1);
  });

  it('asks before it texts the service, and sends nothing until the person says yes', async () => {
    const keys = serveAsk(200);
    const user = userEvent.setup();
    render(<ServiceActions serviceId="svc-a" onCheck={() => undefined} />);
    await user.click(screen.getByRole('button', { name: 'Request capacity update' }));
    expect(keys).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(keys).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Request capacity update' }));
    await user.click(screen.getByRole('button', { name: 'Yes, text the service now' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The service has been asked for its figure');
    expect(keys).toHaveLength(1);
    expect(keys[0]).toBeTruthy();
  });

  it('says so when a request is already waiting (409), and when the request fails', async () => {
    serveAsk(409);
    const user = userEvent.setup();
    const { unmount } = render(<ServiceActions serviceId="svc-a" onCheck={() => undefined} />);
    await user.click(screen.getByRole('button', { name: 'Request capacity update' }));
    await user.click(screen.getByRole('button', { name: 'Yes, text the service now' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('cannot be asked right now'));
    unmount();
    serveAsk(500);
    render(<ServiceActions serviceId="svc-a" onCheck={() => undefined} />);
    await user.click(screen.getByRole('button', { name: 'Request capacity update' }));
    await user.click(screen.getByRole('button', { name: 'Yes, text the service now' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('could not be sent'));
  });
});
