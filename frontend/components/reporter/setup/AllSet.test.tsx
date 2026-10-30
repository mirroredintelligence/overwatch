import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { AllSet } from '@/components/reporter/setup/AllSet';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const subscribeToPush = vi.hoisted(() => vi.fn());
vi.mock('@/lib/push/subscribe', () => ({ subscribeToPush }));

beforeEach(() => {
  push.mockClear();
  resetReporterRequests();
  subscribeToPush.mockReset();
  subscribeToPush.mockResolvedValue({ endpoint: 'https://push.example/x', keys: { p256dh: 'p', auth: 'a' } });
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'granted' }));
});

describe('AllSet', () => {
  it('saves the push subscription with the consent wording version once the reporter is signed in', async () => {
    render(<AllSet />);
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/push/subscriptions')).toBe(true));
    const saved = seenBffRequests.find((r) => r.path === '/api/bff/push/subscriptions');
    expect(saved?.body).toMatchObject({ consentWordingVersion: 'v1' });
  });

  it('shows the summary and the test-notification and go-to-app actions, and passes axe', async () => {
    const { container } = render(<AllSet />);
    expect(await screen.findByRole('heading', { name: 'All set' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send me a test notification' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to the app' })).toHaveAttribute('href', '/app');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('tells the reporter when the subscription could not be saved, and does not claim it was', async () => {
    server.use(http.post('/api/bff/push/subscriptions', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<AllSet />);
    expect(await screen.findByText('We could not save your notification choice. Try again.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Send me a test notification' }));
  });
});
