import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { seenBffRequests, resetReporterRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { SetupFlow } from './SetupFlow';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const INVITE = 'invite-token-sample';

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('SetupFlow', () => {
  it('welcomes the reporter with the service and the five steps, and passes axe', async () => {
    const { container } = render(<SetupFlow step="welcome" invite={INVITE} />);
    expect(await screen.findByRole('heading', { name: 'Set up capacity reporting for UCR West' })).toBeInTheDocument();
    expect(screen.getByText('You can stop and come back to the link within 48 hours.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    expect(push).toHaveBeenCalledWith(`/setup?step=number&invite=${INVITE}`);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the masked number and never the full number', async () => {
    const { container } = render(<SetupFlow step="number" invite={INVITE} />);
    expect(await screen.findByText('07xxx xxx456')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/07\d{9}/);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the resend button only after 60 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<SetupFlow step="code" invite={INVITE} />);
    expect(await screen.findByText(/Send a new code in 0:/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send a new code' })).toBeNull();
    // A second at a time, so each tick is one render (the countdown is one interval).
    for (let second = 0; second < 55; second += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(screen.queryByRole('button', { name: 'Send a new code' })).toBeNull();
    for (let second = 0; second < 10; second += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(await screen.findByRole('button', { name: 'Send a new code' })).toBeInTheDocument();
  });

  it('says how many tries are left after a wrong code', async () => {
    render(<SetupFlow step="code" invite={INVITE} />);
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('000001');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByText('That code is not right. You have 4 tries left.')).toBeInTheDocument();
  });

  it('says to send a new code and disables Check code when no tries are left', async () => {
    server.use(http.post('/api/bff/identity/code/verify', () => HttpResponse.json({ ok: false, triesLeft: 0 })));
    render(<SetupFlow step="code" invite={INVITE} />);
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('000002');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByText('Too many tries. Send a new code.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check code' })).toBeDisabled();
  });

  it('posts Text as the channel and goes to the done page', async () => {
    render(<SetupFlow step="channel" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('radio', { name: /Text message/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/done?channel=text'));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/reporter/channel')?.body).toEqual({ channel: 'text' });
  });

  it('sends App to the home-screen guide', async () => {
    render(<SetupFlow step="channel" invite={INVITE} />);
    await userEvent.click(await screen.findByRole('radio', { name: /App notification/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/home-screen'));
  });

  it('skips the channel step for an exec invitation', async () => {
    server.use(
      http.get('/api/bff/invitations/:token', () =>
        HttpResponse.json({ service: 'ICB board', role: 'exec', maskedPhone: '07xxx xxx456', expiresAt: '2026-11-01T10:00:00Z', state: 'valid' }),
      ),
    );
    render(<SetupFlow step="code" invite={INVITE} />);
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/home-screen'));
    expect(push).not.toHaveBeenCalledWith(expect.stringContaining('step=channel'));
  });
});
