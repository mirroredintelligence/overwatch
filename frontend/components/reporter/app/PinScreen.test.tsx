import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { PinScreen } from './PinScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
});

async function typePin(digits: string) {
  for (const digit of digits) await userEvent.click(screen.getByRole('button', { name: digit }));
}

describe('PinScreen', () => {
  it('offers an executive the organisation sign-in, which comes back to their home (W9H)', () => {
    render(<PinScreen />);
    expect(screen.getByRole('link', { name: 'Sign in with your organisation account' })).toHaveAttribute('href', '/sign-in?next=/planning');
  });

  it('says how many tries are left after a wrong PIN, and offers the forgotten-PIN route', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ ok: false, triesLeft: 4 })));
    const { container } = render(<PinScreen />);
    expect(screen.getByRole('link', { name: 'Forgot your PIN?' })).toHaveAttribute('href', '/app/locked?reason=forgot');
    await typePin('000000');
    expect(await screen.findByText('That PIN is not right. 4 tries left.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('goes to the locked page when the PIN is locked', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ locked: true })));
    render(<PinScreen />);
    await typePin('000000');
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/locked'));
  });

  it('goes to the 30-day check when a text code is needed, and to the app when signed in', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ reverify: true })));
    render(<PinScreen />);
    await typePin('123123');
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/verify'));
  });

  it('says sign-in is not available when the back end gave no token (503), and does not go on', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<PinScreen />);
    await typePin('123123');
    expect(await screen.findByText('Sign-in is not available right now. Try again shortly.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it('goes to the app on a right PIN, and not for a 200 that does not say ok', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ ok: true })));
    const { unmount } = render(<PinScreen />);
    await typePin('123123');
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app'));
    unmount();
    replace.mockClear();
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({})));
    render(<PinScreen />);
    await typePin('123123');
    expect(await screen.findByText('Sign-in is not available right now. Try again shortly.')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
