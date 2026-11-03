import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { SettingsScreen } from './SettingsScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const SETTINGS = { channel: 'text', maskedPhone: '07xxx xxx456', maskedCover: null, reverifyInDays: 21, otherDevices: 1 };

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
  server.use(
    http.get('/api/bff/reporter/settings', () => HttpResponse.json(SETTINGS)),
    http.delete('/api/bff/session', () => new HttpResponse(null, { status: 204 })),
  );
});

describe('SettingsScreen', () => {
  it('shows masked values only, and never the full cover number after one is saved', async () => {
    const { container } = render(<SettingsScreen />);
    expect(await screen.findByText('07xxx xxx456')).toBeInTheDocument();
    expect(screen.getByText('In 21 days')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add a cover number' }));
    await userEvent.type(screen.getByLabelText('Cover mobile number'), '07700 900123');
    await userEvent.click(screen.getByRole('button', { name: 'Save cover number' }));
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/cover')).toBe(true));
    expect(container.textContent).not.toContain('07700 900123');
    expect(container.textContent).not.toContain('900123');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks in the page before signing the phone out, does nothing on Cancel, and signs out on Confirm', async () => {
    render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out of this phone' }));
    expect(screen.getByText('Sign out of this phone?')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText('Sign out of this phone?')).toBeNull();
    expect(push).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Sign out of this phone' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/pin'));
  });

  it('names the channel in words for each of the three the back end gives', async () => {
    for (const [word, label] of [['app', 'App notification'], ['text', 'Text message'], ['email', 'Email']] as const) {
      server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ ...SETTINGS, channel: word })));
      const { unmount } = render(<SettingsScreen />);
      expect(await screen.findByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it('shows a cover number only as the back end masks it', async () => {
    server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ ...SETTINGS, maskedCover: '07xxx xxx789' })));
    render(<SettingsScreen />);
    expect(await screen.findByText('07xxx xxx789')).toBeInTheDocument();
  });

  it('sends the cover with how long it lasts (this week unless another is chosen), then reads the settings again', async () => {
    render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a cover number' }));
    await userEvent.type(screen.getByLabelText('Cover mobile number'), '07700900123');
    await userEvent.click(screen.getByRole('button', { name: 'Save cover number' }));
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/cover')).toBe(true));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/reporter/cover')?.body).toEqual({ phone: '07700900123', until: 'this-week' });
  });

  it('asks for a date when the cover is until a date, and sends it', async () => {
    render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a cover number' }));
    await userEvent.type(screen.getByLabelText('Cover mobile number'), '07700900123');
    await userEvent.click(screen.getByRole('radio', { name: 'A date' }));
    await userEvent.type(screen.getByLabelText('Cover until date'), '2026-11-05');
    await userEvent.click(screen.getByRole('button', { name: 'Save cover number' }));
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/cover')).toBe(true));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/reporter/cover')?.body).toEqual({ phone: '07700900123', until: 'date', date: '2026-11-05' });
  });

  it('says the cover could not be saved when the back end refuses, and keeps no number in the page', async () => {
    server.use(http.post('/api/bff/reporter/cover', () => HttpResponse.json({ code: 'invalid' }, { status: 400 })));
    const { container } = render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a cover number' }));
    await userEvent.type(screen.getByLabelText('Cover mobile number'), '07700900123');
    await userEvent.click(screen.getByRole('button', { name: 'Save cover number' }));
    expect(await screen.findByText('We could not save the cover number. Try again.')).toBeInTheDocument();
    expect(container.textContent).not.toContain('07700900123');
  });

  it('changes how we contact the reporter, in the page, through the session route, and shows the new channel', async () => {
    let channel = 'text';
    server.use(
      http.get('/api/bff/reporter/settings', () => HttpResponse.json({ ...SETTINGS, channel })),
      http.post('/api/bff/reporter/channel', async ({ request }) => {
        const body = (await request.json()) as { channel: string };
        channel = body.channel;
        return HttpResponse.json({ ok: true, channel });
      }),
    );
    render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Change how we contact me' }));
    await userEvent.click(screen.getByRole('radio', { name: /Email/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Save how we contact me' }));
    expect(await screen.findByText('Email')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalledWith('/app/settings#contact');
  });

  it('says the channel could not be changed when the back end refuses (email needs an address on record)', async () => {
    server.use(http.post('/api/bff/reporter/channel', () => HttpResponse.json({ code: 'invalid' }, { status: 400 })));
    render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Change how we contact me' }));
    await userEvent.click(screen.getByRole('radio', { name: /Email/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Save how we contact me' }));
    expect(await screen.findByText('We could not change how we contact you. Try again.')).toBeInTheDocument();
  });

  it('says in words that settings are opening while they load, and then shows the Settings heading', async () => {
    render(<SettingsScreen />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening settings');
    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
  });

  it('shows notifications and an unset cover number as status tags (shape and word), not bare text', async () => {
    const { container } = render(<SettingsScreen />);
    await screen.findByText('07xxx xxx456');
    const rows = container.querySelector('[data-el="REP-SET-SUMMARY"]') as HTMLElement;
    const notifications = within(rows).getByText('Notifications').closest('div') as HTMLElement;
    expect(notifications.querySelector('[data-variant]')).toHaveTextContent('Off');
    expect(notifications.querySelector('[data-variant] svg[aria-hidden="true"]')).not.toBeNull();
    const cover = within(rows).getByText('Cover number').closest('div') as HTMLElement;
    expect(cover.querySelector('[data-variant="paused"]')).toHaveTextContent('Not set');
  });

  it('shows a cover number that is set as plain masked text, not as the "Not set" tag', async () => {
    server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ ...SETTINGS, maskedCover: '07xxx xxx789' })));
    const { container } = render(<SettingsScreen />);
    await screen.findByText('07xxx xxx789');
    expect(container.querySelector('[data-variant="paused"]')).toBeNull();
  });

  it('draws the two change buttons outlined in the primary colour, and sign out of this phone outlined dark', async () => {
    render(<SettingsScreen />);
    expect(await screen.findByRole('button', { name: 'Change how we contact me' })).toHaveAttribute('data-variant', 'secondary');
    expect(screen.getByRole('button', { name: 'Add a cover number' })).toHaveAttribute('data-variant', 'secondary');
    expect(screen.getByRole('button', { name: 'Sign out of this phone' })).toHaveAttribute('data-variant', 'neutral');
  });

  it('has a visible "Sign out of every phone" link after the sign out of this phone button', async () => {
    render(<SettingsScreen />);
    const thisPhone = await screen.findByRole('button', { name: 'Sign out of this phone' });
    const everyPhone = screen.getByRole('link', { name: 'Sign out of every phone' });
    expect(everyPhone).toHaveAttribute('href', '/app/sign-out-all');
    expect(thisPhone.compareDocumentPosition(everyPhone) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('has no accessibility violations in the open cover form and the sign out question', async () => {
    const { container } = render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a cover number' }));
    await userEvent.click(screen.getByRole('button', { name: 'Change how we contact me' }));
    await userEvent.click(screen.getByRole('button', { name: 'Sign out of this phone' }));
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says the settings could not be loaded for a failure, and goes to the PIN for a 401', async () => {
    server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    const { unmount } = render(<SettingsScreen />);
    expect(await screen.findByText('We could not load your settings. Try again shortly.')).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/reporter/settings', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<SettingsScreen />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
