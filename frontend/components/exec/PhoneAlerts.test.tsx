import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { PhoneAlerts } from './PhoneAlerts';

// Alerts on the executive's phone (W9H, DEC-1040 to DEC-1043). The executive uses the notification part
// of the app only: allow, subscribe, save, and a test. Nothing is saved until Allow is pressed; the
// browser's own permission decides whether the prompt appears; the subscription goes to the BFF and
// nowhere else; a refusal is never shown as "on".

const subscribeToPush = vi.hoisted(() => vi.fn());
vi.mock('@/lib/push/subscribe', () => ({ subscribeToPush }));

const SUBSCRIPTION = { endpoint: 'https://push.example/sample-exec', keys: { p256dh: 'p', auth: 'a' } };

function browser(permission: NotificationPermission, requested: NotificationPermission = 'granted') {
  const requestPermission = vi.fn(async () => requested);
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission, requestPermission }));
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { ready: Promise.resolve({}) } });
  return requestPermission;
}

beforeEach(() => {
  resetReporterRequests();
  subscribeToPush.mockReset();
  subscribeToPush.mockResolvedValue(SUBSCRIPTION);
  browser('default');
});

describe('PhoneAlerts', () => {
  it('says what is sent, what never is, who chooses and what is recorded, and asks nothing of the browser yet', () => {
    const requestPermission = browser('default');
    render(<PhoneAlerts />);
    expect(screen.getByRole('heading', { level: 1, name: 'Alerts on this phone' })).toBeInTheDocument();
    expect(screen.getByText(/What we never send: Patient names or details\./)).toBeInTheDocument();
    expect(screen.getByText(/When you allow, we record the date and this phone\./)).toBeInTheDocument();
    expect(requestPermission).not.toHaveBeenCalled();
    expect(seenBffRequests).toEqual([]);
  });

  it('asks the browser, reads the key, subscribes with it and saves with the executive wording, then says alerts are on', async () => {
    server.use(http.get('/api/bff/push/key', () => HttpResponse.json({ publicKey: 'BKeyFromTheBackEnd_01' })));
    const requestPermission = browser('default', 'granted');
    render(<PhoneAlerts />);

    await userEvent.click(screen.getByRole('button', { name: 'Allow alerts on this phone' }));

    expect(await screen.findByText('Alerts are on for this phone.')).toBeInTheDocument();
    expect(requestPermission).toHaveBeenCalledOnce();
    expect(subscribeToPush).toHaveBeenCalledWith(expect.anything(), 'BKeyFromTheBackEnd_01');
    const saved = seenBffRequests.find((r) => r.path === '/api/bff/push/subscriptions');
    expect(saved?.body).toEqual({ subscription: SUBSCRIPTION, consentWordingVersion: 'exec-v1' });
    expect(saved?.idempotencyKey).toMatch(/^[\w-]{8,64}$/);
  });

  it('does not ask again when the browser already allowed alerts, and still saves this phone', async () => {
    const requestPermission = browser('granted');
    render(<PhoneAlerts />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow alerts on this phone' }));
    expect(await screen.findByText('Alerts are on for this phone.')).toBeInTheDocument();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it('says how to turn alerts on when the browser blocks them, and saves nothing', async () => {
    browser('default', 'denied');
    render(<PhoneAlerts />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow alerts on this phone' }));
    expect(await screen.findByText(/Alerts are blocked for this phone\. Turn them on in your phone’s settings, then try again\./)).toBeInTheDocument();
    expect(subscribeToPush).not.toHaveBeenCalled();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/push/subscriptions')).toBe(false);
    expect(screen.queryByText('Alerts are on for this phone.')).not.toBeInTheDocument();
  });

  it('says it could not turn alerts on when the key is not available, and does not claim they are on', async () => {
    server.use(http.get('/api/bff/push/key', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    browser('granted');
    render(<PhoneAlerts />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow alerts on this phone' }));
    expect(await screen.findByText('We could not turn on alerts on this phone. Try again.')).toBeInTheDocument();
    expect(subscribeToPush).not.toHaveBeenCalled();
    expect(screen.queryByText('Alerts are on for this phone.')).not.toBeInTheDocument();
  });

  it('says it could not turn alerts on when the save is refused', async () => {
    server.use(http.post('/api/bff/push/subscriptions', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    browser('granted');
    render(<PhoneAlerts />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow alerts on this phone' }));
    expect(await screen.findByText('We could not turn on alerts on this phone. Try again.')).toBeInTheDocument();
    expect(screen.queryByText('Alerts are on for this phone.')).not.toBeInTheDocument();
  });

  it('says so when this browser cannot show notifications, and offers no Allow button', () => {
    vi.stubGlobal('Notification', undefined);
    render(<PhoneAlerts />);
    expect(screen.getByText(/This browser cannot show notifications\./)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Allow alerts on this phone' })).not.toBeInTheDocument();
  });

  it('sends a test notification and says it is on its way', async () => {
    render(<PhoneAlerts />);
    await userEvent.click(screen.getByRole('button', { name: 'Send me a test notification' }));
    expect(await screen.findByText('A test notification is on its way.')).toBeInTheDocument();
    expect(seenBffRequests.find((r) => r.path === '/api/bff/push/test')?.body).toEqual({});
  });

  it.each([
    [409, 'No alerts are saved for this phone yet. Allow alerts first.'],
    [429, 'You have sent a few test notifications. Try again in a few minutes.'],
    [500, 'We could not send a test notification. Try again.'],
  ])('says what a %s answer to the test means', async (status, words) => {
    server.use(http.post('/api/bff/push/test', () => HttpResponse.json({ code: 'x' }, { status })));
    render(<PhoneAlerts />);
    await userEvent.click(screen.getByRole('button', { name: 'Send me a test notification' }));
    await waitFor(() => expect(screen.getByText(words)).toBeInTheDocument());
    expect(screen.queryByText('A test notification is on its way.')).not.toBeInTheDocument();
  });

  it('links on to the settings and back to the home screen of the executive app', () => {
    render(<PhoneAlerts />);
    expect(screen.getByRole('link', { name: 'Change which alerts I get' })).toHaveAttribute('href', '/planning/settings');
    expect(screen.getByRole('link', { name: 'Done' })).toHaveAttribute('href', '/planning');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<PhoneAlerts />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
