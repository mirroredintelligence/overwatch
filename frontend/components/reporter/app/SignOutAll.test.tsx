import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { SignOutAll } from './SignOutAll';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const SETTINGS = { channel: 'text', maskedPhone: '07xxx xxx456', maskedCover: null, reverifyInDays: 21, otherDevices: 1 };

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
  server.use(
    http.get('/api/bff/reporter/settings', () => HttpResponse.json(SETTINGS)),
    http.post('/api/bff/identity/sign-out-everywhere', () => HttpResponse.json({ ok: true })),
  );
});

describe('SignOutAll', () => {
  it('asks the question, says why, and counts the other phones', async () => {
    const { container } = render(<SignOutAll />);
    expect(screen.getByRole('heading', { level: 1, name: 'Sign out of every phone?' })).toBeInTheDocument();
    expect(screen.getByText(/Use this if a phone is lost, shared or stolen/)).toBeInTheDocument();
    expect(await screen.findByText('This phone and 1 other will be signed out.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says "others" for more than one other phone', async () => {
    server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ ...SETTINGS, otherDevices: 3 })));
    render(<SignOutAll />);
    expect(await screen.findByText('This phone and 3 others will be signed out.')).toBeInTheDocument();
  });

  it('draws the confirm button dark, not red and not the primary blue, and Cancel outlined', async () => {
    render(<SignOutAll />);
    const confirm = screen.getByRole('button', { name: 'Sign out of all phones' });
    expect(confirm).toHaveAttribute('data-variant', 'dark');
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveAttribute('data-variant', 'secondary');
  });

  it('goes back to settings on Cancel and signs nothing out', async () => {
    let sent = 0;
    server.use(
      http.post('/api/bff/identity/sign-out-everywhere', () => {
        sent += 1;
        return HttpResponse.json({ ok: true });
      }),
    );
    render(<SignOutAll />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(push).toHaveBeenCalledWith('/app/settings');
    expect(sent).toBe(0);
  });

  it('signs out everywhere on Confirm and shows the PIN screen', async () => {
    let sent = 0;
    server.use(
      http.post('/api/bff/identity/sign-out-everywhere', () => {
        sent += 1;
        return HttpResponse.json({ ok: true });
      }),
    );
    render(<SignOutAll />);
    await userEvent.click(screen.getByRole('button', { name: 'Sign out of all phones' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/pin'));
    expect(sent).toBe(1);
  });

  it('says it could not sign out when the back end refuses, and lets the person try again', async () => {
    server.use(http.post('/api/bff/identity/sign-out-everywhere', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<SignOutAll />);
    await userEvent.click(screen.getByRole('button', { name: 'Sign out of all phones' }));
    expect(await screen.findByText('We could not sign out your phones. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalledWith('/app/pin');
    expect(screen.getByRole('button', { name: 'Sign out of all phones' })).toBeEnabled();
  });

  it('goes to the PIN when the session has already ended', async () => {
    server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<SignOutAll />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
