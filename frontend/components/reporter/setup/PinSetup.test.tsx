import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { PinSetup } from './PinSetup';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

beforeEach(() => {
  push.mockClear();
  resetReporterRequests();
});

async function type(digits: string) {
  for (const digit of digits) await userEvent.click(screen.getByRole('button', { name: digit }));
}

describe('PinSetup', () => {
  it('is step 5 of 5 in the provider shell, with the explanation and the no-button hint', () => {
    render(<PinSetup />);
    expect(screen.getByRole('progressbar', { name: 'Step 5 of 5' })).toBeInTheDocument();
    expect(screen.getByText('Step 5 of 5')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByText('You enter it each time you open the app. We text you a code again every 30 days.')).toBeInTheDocument();
    expect(screen.getByText('At six digits we ask you to enter it once more. No button to press.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('0 of 6 digits entered');
  });

  it('has no Continue button: the sixth digit moves on by itself, and the dots start empty again', async () => {
    render(<PinSetup />);
    expect(screen.queryByRole('button', { name: /continue/i })).toBeNull();
    await type('12345');
    expect(screen.getByRole('status')).toHaveTextContent('5 of 6 digits entered');
    await type('6');
    expect(screen.getByRole('heading', { name: 'Enter it again' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('0 of 6 digits entered');
    expect(screen.queryByRole('button', { name: /continue/i })).toBeNull();
  });

  it('says the PINs do not match, restarts, and posts nothing', async () => {
    const { container } = render(<PinSetup />);
    await type('123456');
    expect(screen.getByRole('heading', { name: 'Enter it again' })).toBeInTheDocument();
    await type('654321');
    expect(await screen.findByText('The PINs do not match. Try again.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Create a 6-digit PIN' })).toBeInTheDocument();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/identity/pin')).toBe(false);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('posts a matching PIN once and then signs the reporter in', async () => {
    render(<PinSetup />);
    await type('123456');
    await type('123456');
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/all-set'));
    const posts = seenBffRequests.filter((r) => r.path === '/api/bff/identity/pin');
    expect(posts).toEqual([{ path: '/api/bff/identity/pin', method: 'POST', body: { pin: '123456' } }]);
  });

  it('shows the error and stays on the PIN when the back end refuses the set', async () => {
    server.use(http.post('/api/bff/identity/pin', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<PinSetup />);
    await type('123456');
    await type('123456');
    expect(await screen.findByText('Get a code by text first.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('does not go on when the sign-in after the PIN is set is not a right PIN (a 200 that says ok: false), and says so', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ ok: false, triesLeft: 4 })));
    render(<PinSetup />);
    await type('123456');
    await type('123456');
    expect(await screen.findByText('We could not sign you in. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('does not go on when the sign-in could not be completed (the back end gave no token): 503', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<PinSetup />);
    await type('123456');
    await type('123456');
    expect(await screen.findByText('We could not sign you in. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
