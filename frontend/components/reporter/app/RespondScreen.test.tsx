import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { RespondScreen } from './RespondScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const SERVICE = 'svc-1';

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

describe('RespondScreen', () => {
  it('confirms the figure on record with "Yes, still 3" and goes to the thanks page', async () => {
    const { container } = render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(push.mock.calls[0][0]).toContain(`/app/respond/${SERVICE}/thanks`);
    expect(seenBffRequests.find((r) => r.path.endsWith('/report'))?.body).toEqual({ kind: 'confirm' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('sends the number on the stepper with Send new number', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    const stepper = await screen.findByRole('textbox');
    await userEvent.clear(stepper);
    await userEvent.type(stepper, '4');
    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(seenBffRequests.find((r) => r.path.endsWith('/report'))?.body).toEqual({ kind: 'number', value: 4 });
  });

  it('keeps the number and shows the range message for an out-of-range figure', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    const stepper = await screen.findByRole('textbox');
    await userEvent.clear(stepper);
    await userEvent.type(stepper, '9');
    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    expect(await screen.findByText('That is outside your usual range (0 to 8). Send it again to confirm.')).toBeInTheDocument();
    expect(stepper).toHaveValue('9');
  });

  it('hides the confirm button and shows the message when two confirms are already used', async () => {
    server.use(
      http.post('/api/bff/reporter/services/:serviceId/report', () =>
        HttpResponse.json({ result: 'confirmLimit' }, { status: 409 }),
      ),
    );
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('You confirmed twice already. Please send the number.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes, still 3' })).toBeNull();
  });

  it('with no recorded figure, the primary button is disabled until a number is chosen', async () => {
    server.use(
      http.get('/api/bff/reporter/services/:serviceId/prompt', () =>
        HttpResponse.json({ service: 'UCR West', unitLabel: 'referrals in the next 2 hrs', recordedValue: null, asOf: null, low: 0, high: 8, replyBy: '10:30', nextDue: '12:00' }),
      ),
    );
    render(<RespondScreen serviceId={SERVICE} />);
    expect(await screen.findByText('How many referrals can you take in the next 2 hrs?')).toBeInTheDocument();
    const primary = screen.getByRole('button', { name: 'Choose a number to send' });
    expect(primary).toBeDisabled();
  });

  it('sends a 401 to the PIN screen', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/prompt', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })));
    render(<RespondScreen serviceId={SERVICE} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });

  it('says when the figure on record is from, in London clock time', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    expect(await screen.findByText('We have 3 referrals in the next 2 hrs, as of 08:15. Still right?')).toBeInTheDocument();
  });

  it('sends each answer with its own Idempotency-Key', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    const key = seenBffRequests.find((r) => r.path.endsWith('/report'))?.idempotencyKey;
    expect(key).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });

  it('carries the recorded figure to the thanks page as the back end gave it: the service, the figure and the instants', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    const query = new URLSearchParams(String(push.mock.calls[0][0]).split('?')[1]);
    expect(Object.fromEntries(query)).toEqual({ service: 'UCR West', unit: 'referrals in the next 2 hrs', value: '3', at: '2026-10-30T10:12:00Z', next: '2026-10-30T12:00:00Z' });
  });

  it('uses the range the back end names for a figure out of range, and confirms it with the next send of the same figure', async () => {
    render(<RespondScreen serviceId={SERVICE} />);
    const stepper = await screen.findByRole('textbox');
    await userEvent.clear(stepper);
    await userEvent.type(stepper, '9');
    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    await screen.findByText('That is outside your usual range (0 to 8). Send it again to confirm.');
    await userEvent.click(screen.getByRole('button', { name: 'Send new number' }));
    await waitFor(() => expect(seenBffRequests.filter((r) => r.path.endsWith('/report'))).toHaveLength(2));
    expect(seenBffRequests.filter((r) => r.path.endsWith('/report')).map((r) => r.body)).toEqual([
      { kind: 'number', value: 9 },
      { kind: 'number', value: 9, confirmOutOfRange: true },
    ]);
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

  it('never goes to the thanks page for an answer that is not recorded', async () => {
    server.use(http.post('/api/bff/reporter/services/:serviceId/report', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    expect(await screen.findByText('We could not record that. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('says the service could not be loaded for a 404 or a failure, and goes to the PIN only for a 401', async () => {
    server.use(http.get('/api/bff/reporter/services/:serviceId/prompt', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<RespondScreen serviceId={SERVICE} />);
    expect(await screen.findByText('We could not load this service. Try again shortly.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('goes to the PIN when a write finds the session has ended', async () => {
    server.use(http.post('/api/bff/reporter/services/:serviceId/report', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<RespondScreen serviceId={SERVICE} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, still 3' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
