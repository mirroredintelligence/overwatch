import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { RespondScreen } from './RespondScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const SERVICE = 'svc-1';

const reports = () => seenBffRequests.filter((r) => r.path.endsWith('/report'));

const NO_FIGURE = {
  service: 'UCR West',
  unitLabel: 'referrals in the next 2 hrs',
  recordedValue: null,
  asOf: null,
  low: 0,
  high: 8,
  replyBy: '2026-10-30T10:30:00Z',
  nextDue: '2026-10-30T12:00:00Z',
};

/** Opens the stepper with "Send a different number" and types a figure into it. */
async function typeFigure(text: string) {
  await userEvent.click(await screen.findByRole('button', { name: 'Send a different number' }));
  const box = screen.getByRole('textbox');
  await userEvent.clear(box);
  await userEvent.type(box, text);
  return box;
}

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RespondScreen', () => {
  it('says what is being opened while the prompt loads, as a polite status', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening the update.');
    await screen.findByRole('heading', { name: 'UCR West' });
  });

  it('shows the figure card: label, reply-by, the figure on record, when it was recorded, and the three ways to answer', async () => {
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Capacity update')).toBeInTheDocument();
    expect(screen.getByText('Reply by 10:30')).toBeInTheDocument();
    expect(container.querySelector('[data-figure="3"]')).toHaveTextContent('3');
    expect(screen.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Recorded at 08:15. Still right?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes, still 3' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send a different number' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: 'We are closed to referrals' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByText('Next update due 12:00.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('confirms the figure on record with "Yes, still 3" and goes to the thanks page', async () => {
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(push.mock.calls[0][0]).toContain(`/app/respond/${SERVICE}/thanks`);
    expect(reports()[0]?.body).toEqual({ kind: 'confirm' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('opens the stepper in place for a different number, keeps the figure card, and sends the number', async () => {
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    await typeFigure('4');
    expect(container.querySelector('[data-figure="3"]')).not.toBeNull();
    expect(screen.getByText('referrals, usual range 0 to 8')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes, still 3' })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: 'Send 4' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(reports()[0]?.body).toEqual({ kind: 'number', value: 4 });
  });

  it('moves focus to the new heading after each step', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'We are closed to referrals' }));
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveFocus());
  });

  it('asks once for a figure far outside the usual range, keeping it, and confirms it with the same figure', async () => {
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    await typeFigure('9');
    await userEvent.click(screen.getByRole('button', { name: 'Send 9' }));
    expect(await screen.findByText('Is 9 right?')).toBeInTheDocument();
    expect(screen.getByText(/That is far above your usual range of 0 to 8\./)).toBeInTheDocument();
    expect(screen.getByText('Nothing is recorded until you press a button.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, send 9' }));
    await waitFor(() => expect(reports()).toHaveLength(2));
    expect(reports().map((r) => r.body)).toEqual([
      { kind: 'number', value: 9 },
      { kind: 'number', value: 9, confirmOutOfRange: true },
    ]);
  });

  it('goes back to the stepper with the number kept from "Change the number"', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    await typeFigure('9');
    await userEvent.click(screen.getByRole('button', { name: 'Send 9' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Change the number' }));
    expect(screen.getByRole('textbox')).toHaveValue('9');
    expect(push).not.toHaveBeenCalled();
  });

  it('asks before telling advisors the service is closed, and posts nothing until "Yes, we are closed"', async () => {
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'We are closed to referrals' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Tell advisors UCR West is closed?' })).toBeInTheDocument();
    expect(screen.getByText('You can send a number later from the next prompt, or phone the shift lead.')).toBeInTheDocument();
    expect(reports()).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: 'No, go back' }));
    expect(await screen.findByRole('button', { name: 'Yes, still 3' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'We are closed to referrals' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, we are closed' }));
    await waitFor(() => expect(reports()).toHaveLength(1));
    expect(reports()[0]?.body).toEqual({ kind: 'closed' });
  });

  it('hides the confirm and shows the stepper with the message when two confirms are already used', async () => {
    server.use(http.post('/api/bff/reporter/services/:serviceId/report', () => HttpResponse.json({ result: 'confirmLimit' }, { status: 409 })));
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('You confirmed twice already. Please send the number.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes, still 3' })).toBeNull();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });

  it('asks for the number, and hides the confirm, when the back end says a confirm cannot stand (409 sendNumber)', async () => {
    server.use(
      http.post('/api/bff/reporter/services/:serviceId/report', () => HttpResponse.json({ result: 'sendNumber', serviceName: 'UCR West', reason: 'stale' }, { status: 409 })),
    );
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('We cannot confirm that figure now. Please send the number.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes, still 3' })).toBeNull();
    expect(push).not.toHaveBeenCalled();
  });

  it('with no recorded figure, asks the first question and the primary button is disabled until a number is chosen', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/prompt', () => HttpResponse.json(NO_FIGURE)));
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    expect(await screen.findByText('How many referrals can you take in the next 2 hrs?')).toBeInTheDocument();
    expect(screen.getByText('First update')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('');
    const primary = screen.getByRole('button', { name: 'Choose a number to send' });
    expect(primary).toBeDisabled();
    expect(screen.getByRole('button', { name: 'We are closed to referrals' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.type(screen.getByRole('textbox'), '2');
    await userEvent.click(screen.getByRole('button', { name: 'Send 2' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(reports()[0]?.body).toEqual({ kind: 'number', value: 2 });
  });

  it('sends a 401 to the PIN screen', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/prompt', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })));
    render(<RespondScreen serviceId={SERVICE} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });

  it('sends each answer with its own Idempotency-Key', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(reports()[0]?.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });

  it('carries the recorded figure to the thanks page as the back end gave it: the service, the figure and the instants', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    const query = new URLSearchParams(String(push.mock.calls[0][0]).split('?')[1]);
    expect(Object.fromEntries(query)).toEqual({ service: 'UCR West', unit: 'referrals', value: '3', at: '2026-10-30T10:12:00Z', next: '2026-10-30T12:00:00Z' });
  });

  it('never goes to the thanks page for an answer that is not recorded, and keeps the answer to send again', async () => {
    server.use(http.post('/api/bff/reporter/services/:serviceId/report', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    const banner = await screen.findByRole('alert');
    expect(within(banner).getByText('We could not send that.')).toBeInTheDocument();
    expect(banner).toHaveTextContent('Your number is still here. Try again, or phone the shift lead.');
    expect(screen.getByText('Not sent yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again now' })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says there is no signal when the phone is offline, then sends the same answer again with the same Idempotency-Key', async () => {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false);
    const keys: (string | null)[] = [];
    server.use(
      http.post('/api/bff/reporter/services/:serviceId/report', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        const attempts = keys.length;
        if (attempts === 1) return HttpResponse.error();
        return HttpResponse.json({ result: 'recorded', serviceName: 'UCR West', value: 3, recordedAt: '2026-10-30T10:12:00Z', nextDue: null });
      }),
    );
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent('No signal. Not sent yet.');
    expect(banner).toHaveTextContent('Nothing has been lost.');
    await userEvent.click(screen.getByRole('button', { name: 'Try again now' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(keys).toHaveLength(2);
    expect(keys[0]).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    expect(keys[0]).toBe(keys[1]);
  });

  it('says the service could not be loaded for a 404 or a failure, and goes to the PIN only for a 401', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/prompt', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<RespondScreen serviceId={SERVICE} />);
    expect(await screen.findByText('We could not load this service.')).toBeInTheDocument();
    expect(screen.getByText(/Try again shortly\./)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('goes to the PIN when a write finds the session has ended', async () => {
    server.use(http.post('/api/bff/reporter/services/:serviceId/report', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
