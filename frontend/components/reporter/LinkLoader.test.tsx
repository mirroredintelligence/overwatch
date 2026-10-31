import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { csrfFor, LINK, renewCsrfFor } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts, seenBffReads, seenBffRenewCsrf, seenBffRenews } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { LinkLoader } from './LinkLoader';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

beforeEach(() => {
  resetLinkRequests();
  replace.mockClear();
});

describe('LinkLoader', () => {
  it('shows the link’s figure and its question once it has read the link', async () => {
    const { container } = render(<LinkLoader token={LINK.recorded} />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening your link');
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('We have 3 referrals in the next 2 hrs, as of 08:15. Still right?')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('makes no POST when the link is read, to the BFF or the back end', async () => {
    render(<LinkLoader token={LINK.recorded} />);
    await screen.findByRole('button', { name: 'Yes, still 3' });
    expect(seenBffPosts).toHaveLength(0);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('shows the expired message for an expired link, without a figure', async () => {
    const { container } = render(<LinkLoader token={LINK.expired} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This link has expired' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send me a new link' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the same expired message for a used link as for an expired one, word for word', async () => {
    const { container, unmount } = render(<LinkLoader token={LINK.expired} />);
    await screen.findByRole('heading', { level: 1, name: 'This link has expired' });
    const expired = container.textContent;
    unmount();
    const used = render(<LinkLoader token={LINK.used} />);
    await screen.findByRole('heading', { level: 1, name: 'This link has expired' });
    expect(used.container.textContent).toBe(expired);
  });

  it('says the link could not be loaded, and does not say it expired, when the back end is down', async () => {
    render(<LinkLoader token={LINK.down} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
    expect(screen.queryByText('This link has expired')).toBeNull();
  });

  it('says the link could not be loaded when the BFF answers with an error the page does not know', async () => {
    server.use(http.get('/api/bff/links/:token', () => HttpResponse.json({}, { status: 500 })));
    render(<LinkLoader token={LINK.recorded} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });

  it('says the link could not be loaded when the answer is not a link the page can read', async () => {
    server.use(http.get('/api/bff/links/:token', () => HttpResponse.json({ state: 'ok' }, { status: 200 })));
    render(<LinkLoader token={LINK.recorded} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });

  it('shows a booking request in place, and reads the link once (KI-651)', async () => {
    render(<LinkLoader token={LINK.booking} />);
    expect(await screen.findByRole('button', { name: 'Confirm booking' })).toBeInTheDocument();
    expect(screen.getByText('Need fall, no injury and frailty')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(seenBffReads).toEqual([LINK.booking]);
  });

  it('answers a booking request it showed with the CSRF token of that one read', async () => {
    render(<LinkLoader token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Booked' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([{ token: LINK.booking, body: { action: 'confirm' }, csrf: csrfFor(LINK.booking) }]);
    expect(seenBffReads).toEqual([LINK.booking]);
  });

  it('shows a confirmed booking’s change page in place, and reads the link once', async () => {
    render(<LinkLoader token={LINK.bookingChange} />);
    expect(await screen.findByRole('button', { name: 'We cannot take this patient now' })).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(seenBffReads).toEqual([LINK.bookingChange]);
  });

  it('shows a closed booking link as a closed booking, with its reference, the time and the number (H-486)', async () => {
    const { container } = render(<LinkLoader token={LINK.bookingExpired} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This request has closed' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821. Closed at 14:26.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toHaveAttribute('href', 'tel:0300 123 4567');
    expect(screen.queryByRole('button', { name: 'Send me a new link' })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a cancelled booking as cancelled, with when and the number', async () => {
    render(<LinkLoader token={LINK.bookingCancelled} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Cancelled by the coordination team' })).toBeInTheDocument();
    expect(screen.getByText('Booking 4821 was cancelled at 14:40. No action needed.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toBeInTheDocument();
  });

  it('gives a closed capacity link its renewal CSRF token, and asks for a new link with it', async () => {
    render(<LinkLoader token={LINK.expired} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send me a new link' }));
    expect(await screen.findByText('We have sent a new link.')).toBeInTheDocument();
    expect(seenBffRenews).toEqual([LINK.expired]);
    expect(seenBffRenewCsrf).toEqual([renewCsrfFor(LINK.expired)]);
  });

  it('says the link could not be loaded for a purpose this page does not serve', async () => {
    server.use(
      http.get('/api/bff/links/:token', () =>
        HttpResponse.json({
          state: 'ok',
          purpose: 'something-else',
          serviceName: 'UCR West',
          unitLabel: 'referrals in the next 2 hrs',
          recordedValue: 3,
          asOf: '2026-10-23T07:15:00Z',
          usualMin: 0,
          usualMax: 8,
          replyBy: '2026-10-23T09:30:00Z',
          nextDue: null,
          csrfToken: 'csrf-x',
        }),
      ),
    );
    render(<LinkLoader token={LINK.recorded} />);
    expect(await screen.findByText('We could not load this link. Try again in a few minutes.')).toBeInTheDocument();
  });
});
