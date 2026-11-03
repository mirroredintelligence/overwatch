import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { AllSet } from '@/components/reporter/setup/AllSet';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const subscribeToPush = vi.hoisted(() => vi.fn());
vi.mock('@/lib/push/subscribe', () => ({ subscribeToPush }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
  subscribeToPush.mockReset();
  subscribeToPush.mockResolvedValue({ endpoint: 'https://push.example/x', keys: { p256dh: 'p', auth: 'a' } });
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'granted' }));
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { ready: Promise.resolve({}) } });
});

describe('AllSet', () => {
  it('saves the push subscription with the consent wording version once the reporter is signed in', async () => {
    render(<AllSet />);
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/push/subscriptions')).toBe(true));
    const saved = seenBffRequests.find((r) => r.path === '/api/bff/push/subscriptions');
    expect(saved?.body).toMatchObject({ consentWordingVersion: 'v1' });
  });

  it('shows the success heading, the lead line and one Open Overwatch action, and passes axe', async () => {
    const { container } = render(<AllSet />);
    expect(await screen.findByRole('heading', { level: 1, name: 'You are all set' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Overwatch' })).toHaveAttribute('href', '/app');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the test-notification action beside the summary, as before', async () => {
    render(<AllSet />);
    expect(await screen.findByRole('button', { name: 'Send me a test notification' })).toBeInTheDocument();
  });

  it('shows a shimmer in the shape of the summary while it loads, with a spoken label', () => {
    render(<AllSet />);
    expect(screen.getByText('Loading your set-up summary.')).toBeInTheDocument();
  });

  it('tells the reporter when the subscription could not be saved, and does not claim it was', async () => {
    server.use(http.post('/api/bff/push/subscriptions', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<AllSet />);
    expect(await screen.findByText('We could not save your notification choice. Try again.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Send me a test notification' }));
  });

  it('reads the public key from the BFF and subscribes the browser with it, before anything is saved', async () => {
    server.use(http.get('/api/bff/push/key', () => HttpResponse.json({ publicKey: 'BKeyFromTheBackEnd_01' })));
    render(<AllSet />);
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/push/subscriptions')).toBe(true));
    expect(subscribeToPush).toHaveBeenCalledWith(expect.anything(), 'BKeyFromTheBackEnd_01');
    const saved = seenBffRequests.find((r) => r.path === '/api/bff/push/subscriptions');
    expect(saved?.body).toEqual({ subscription: { endpoint: 'https://push.example/x', keys: { p256dh: 'p', auth: 'a' } }, consentWordingVersion: 'v1' });
  });

  it('does not save anything, and says so, when the public key is not available', async () => {
    server.use(http.get('/api/bff/push/key', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    render(<AllSet />);
    expect(await screen.findByText('We could not save your notification choice. Try again.')).toBeInTheDocument();
    expect(subscribeToPush).not.toHaveBeenCalled();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/push/subscriptions')).toBe(false);
  });

  it('does not ask for a subscription when notifications were not allowed', async () => {
    vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'denied' }));
    render(<AllSet />);
    await screen.findByRole('heading', { name: 'You are all set' });
    expect(subscribeToPush).not.toHaveBeenCalled();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/push/subscriptions')).toBe(false);
  });

  it('shows four rows in words: the service, how we contact, the number as masked and the next update in clock time', async () => {
    render(<AllSet />);
    expect((await screen.findByText('Service')).nextElementSibling).toHaveTextContent('UCR West');
    expect(screen.getByText('We contact you by')).toBeInTheDocument();
    expect(screen.getByText('App notification')).toBeInTheDocument();
    expect(screen.getByText('Phone')).toBeInTheDocument();
    expect(screen.getByText('07xxx xxx456')).toBeInTheDocument();
    expect(screen.getByText('Next update due')).toBeInTheDocument();
    expect(screen.getAllByText('12:00').length).toBeGreaterThan(0);
  });

  it('drops the role and PIN rows, which the summary does not carry', async () => {
    render(<AllSet />);
    await screen.findByText('Next update due');
    expect(screen.queryByText('Your role')).toBeNull();
    expect(screen.queryByText('PIN')).toBeNull();
  });

  it('says the first request time in the lead line when the summary has one', async () => {
    render(<AllSet />);
    expect(await screen.findByText(/Your first request arrives at/)).toBeInTheDocument();
  });

  it('says how the answers work, without a time, when there is no next update', async () => {
    server.use(
      http.get('/api/bff/reporter/setup-summary', () =>
        HttpResponse.json({ service: 'UCR West', contactBy: 'text', maskedPhone: '07xxx xxx456', nextUpdateDue: null, textCodeInDays: 1 }),
      ),
    );
    render(<AllSet />);
    expect(await screen.findByText('Not set')).toBeInTheDocument();
    expect(screen.getByText('Answer each request the way you will every time: pick the number and send.')).toBeInTheDocument();
    expect(screen.queryByText(/Your first request arrives at/)).toBeNull();
  });

  it.each([
    ['text', 'Text message'],
    ['email', 'Email'],
  ])('says %s as %s', async (word, label) => {
    server.use(
      http.get('/api/bff/reporter/setup-summary', () =>
        HttpResponse.json({ service: 'UCR West', contactBy: word, maskedPhone: '07xxx xxx456', nextUpdateDue: null, textCodeInDays: 1 }),
      ),
    );
    render(<AllSet />);
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByText('Not set')).toBeInTheDocument();
  });

  it('says the summary could not be loaded, and does not show a made-up one', async () => {
    server.use(http.get('/api/bff/reporter/setup-summary', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    render(<AllSet />);
    expect(await screen.findByText('We could not load your summary. Your set-up is saved.')).toBeInTheDocument();
    expect(screen.queryByText('Service')).toBeNull();
    expect(screen.queryByText('Loading your set-up summary.')).toBeNull();
  });

  it('sends the test notification and says it is on its way', async () => {
    render(<AllSet />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send me a test notification' }));
    expect(await screen.findByText('A test notification is on its way.')).toBeInTheDocument();
    expect(seenBffRequests.some((r) => r.path === '/api/bff/push/test')).toBe(true);
  });

  it.each([
    [409, { code: 'no-subscription' }, 'No notification is saved for this phone yet. Allow notifications first.'],
    [429, { code: 'throttled' }, 'You have sent a few test notifications. Try again in a few minutes.'],
    [503, { code: 'unavailable' }, 'We could not send a test notification. Try again.'],
  ])('says what happened when the test notification answers %i', async (status, body, text) => {
    server.use(http.post('/api/bff/push/test', () => HttpResponse.json(body, { status })));
    render(<AllSet />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send me a test notification' }));
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it('goes to the sign-in when the session has ended (a 401 from any call)', async () => {
    server.use(http.get('/api/bff/reporter/setup-summary', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<AllSet />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
