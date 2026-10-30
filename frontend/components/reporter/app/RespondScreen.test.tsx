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
});
