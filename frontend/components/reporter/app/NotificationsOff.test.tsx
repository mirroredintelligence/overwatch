import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { NotificationsOff } from './NotificationsOff';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
});

describe('NotificationsOff', () => {
  it('explains the three steps and passes axe', async () => {
    const { container } = render(<NotificationsOff />);
    expect(screen.getByRole('heading', { name: 'Notifications are off' })).toBeInTheDocument();
    expect(screen.getByText('We cannot alert you. Turn them on in your phone settings, or switch to text.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says they are still off when permission is still denied, and goes back to settings when granted', async () => {
    vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'denied' }));
    render(<NotificationsOff />);
    await userEvent.click(screen.getByRole('button', { name: 'I have turned them on' }));
    expect(await screen.findByText('Notifications are still off.')).toBeInTheDocument();
    vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'granted' }));
    await userEvent.click(screen.getByRole('button', { name: 'I have turned them on' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/settings'));
    vi.unstubAllGlobals();
  });

  it('records text behind the session when the reporter is signed in (from Settings)', async () => {
    const { resetReporterRequests, seenBffRequests } = await import('@/test/msw/handlers/reporter');
    resetReporterRequests();
    render(<NotificationsOff />);
    await userEvent.click(screen.getByRole('button', { name: 'Use text instead' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/done?channel=text'));
    expect(seenBffRequests.map((r) => r.path)).toEqual(['/api/bff/reporter/channel']);
  });

  it('records text for the phone’s device when there is no session yet (from set-up)', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    const { resetReporterRequests, seenBffRequests } = await import('@/test/msw/handlers/reporter');
    resetReporterRequests();
    server.use(http.post('/api/bff/reporter/channel', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })));
    render(<NotificationsOff />);
    await userEvent.click(screen.getByRole('button', { name: 'Use text instead' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/done?channel=text'));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/channel')?.body).toEqual({ channel: 'text' });
  });

  it('says so, and does not go on, when neither route could record it', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(
      http.post('/api/bff/reporter/channel', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })),
      http.post('/api/bff/identity/channel', () => HttpResponse.json({ code: 'needs-code' }, { status: 403 })),
    );
    push.mockClear();
    render(<NotificationsOff />);
    await userEvent.click(screen.getByRole('button', { name: 'Use text instead' }));
    expect(await screen.findByText('We could not change how we contact you. Check your number again, then try once more.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
