import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOOKING_CHANGE_TOKEN, csrfFor, LINK } from '@/test/fixtures/links';
import { resetLinkRequests, seenBackendRequests, seenBffPosts } from '@/test/msw/handlers/links';
import { BookingDecision } from './BookingDecision';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

// The service's booking request page (L02, W19). Sample values only: booking 4821, UCR West.

beforeEach(() => {
  resetLinkRequests();
  replace.mockClear();
});

describe('BookingDecision: an open request', () => {
  it('shows the reference, the service, the three rows and the footer', async () => {
    const { container } = render(<BookingDecision token={LINK.booking} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('DIUCS booking request · Reference 4821')).toBeInTheDocument();
    expect(screen.getByText('Age band 80+')).toBeInTheDocument();
    expect(screen.getByText('Need fall-no-injury and frailty')).toBeInTheDocument();
    expect(screen.getByText('Response wanted Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Referral details follow in SystmOne.')).toBeInTheDocument();
    expect(screen.getByText('Not booked until you confirm. Reply by 14:26.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('posts nothing while it renders', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await screen.findByRole('heading', { level: 1, name: 'UCR West' });
    expect(seenBffPosts).toHaveLength(0);
  });

  it('confirms with the CSRF header and shows Booked with the reference and the change link', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Booked' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([{ token: LINK.booking, body: { action: 'confirm' }, csrf: csrfFor(LINK.booking) }]);
    expect(screen.getByText('Reference 4821, UCR West. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByText('Referral details follow in SystmOne.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toHaveAttribute('href', 'tel:0300 123 4567');
    expect(screen.getByRole('link', { name: 'Tell us something changed' })).toHaveAttribute(
      'href',
      `/l/${BOOKING_CHANGE_TOKEN}/booking/change`,
    );
    expect(screen.getByText('You can close this page.')).toBeInTheDocument();
  });

  it('declines with the chosen reason', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Outside our criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([
      { token: LINK.booking, body: { action: 'decline', reason: 'outside-criteria' }, csrf: csrfFor(LINK.booking) },
    ]);
    expect(screen.getByText('Reference 4821 declined. The advisor has been told.')).toBeInTheDocument();
  });

  it('declines without a reason when no chip is chosen, and sends no reason field', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Decline' }));
    await screen.findByRole('heading', { level: 1, name: 'Declined' });
    expect(seenBffPosts[0]?.body).toEqual({ action: 'decline' });
    expect(seenBffPosts[0]?.body).not.toHaveProperty('reason');
  });

  it('lets a chip be chosen once and unchosen again, with aria-pressed', async () => {
    render(<BookingDecision token={LINK.booking} />);
    const full = await screen.findByRole('button', { name: 'We are full' });
    expect(full).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(full);
    expect(full).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(full);
    expect(full).toHaveAttribute('aria-pressed', 'false');
  });

  it('keeps the four reasons with their data-el ids', async () => {
    render(<BookingDecision token={LINK.booking} />);
    expect(await screen.findByRole('button', { name: 'We are full' })).toHaveAttribute('data-el', 'SVC-BOOK-REASON-FULL');
    expect(screen.getByRole('button', { name: 'Outside our criteria' })).toHaveAttribute('data-el', 'SVC-BOOK-REASON-OUTSIDE');
    expect(screen.getByRole('button', { name: 'Staffing or transport' })).toHaveAttribute('data-el', 'SVC-BOOK-REASON-STAFFING');
    expect(screen.getByRole('button', { name: 'Other' })).toHaveAttribute('data-el', 'SVC-BOOK-REASON-OTHER');
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toHaveAttribute('data-el', 'SVC-BOOK-CONFIRM-BTN');
    expect(screen.getByRole('button', { name: 'Decline' })).toHaveAttribute('data-el', 'SVC-BOOK-DECLINE-BTN');
  });
});

describe('BookingDecision: closed and taken links', () => {
  it('shows the closed page when the link is closed on opening, and posts nothing', async () => {
    const { container } = render(<BookingDecision token={LINK.bookingDeclined} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This request has closed' })).toBeInTheDocument();
    expect(screen.getByText('If you can still take this patient, phone the SPOA.')).toBeInTheDocument();
    expect(seenBffPosts).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the matching final page when the answer is refused as already declined (409)', async () => {
    render(<BookingDecision token={LINK.bookingTaken} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Decline' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(1);
  });

  it('is clean for axe on the booked and declined pages', async () => {
    const { container, unmount } = render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    await screen.findByRole('heading', { level: 1, name: 'Booked' });
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();
    const declined = render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Decline' }));
    await screen.findByRole('heading', { level: 1, name: 'Declined' });
    expect(await runAxe(declined.container)).toHaveNoViolations();
  });
});

describe('BookingDecision: a change link opened by mistake', () => {
  it('sends a booking-change link on to its own page', async () => {
    render(<BookingDecision token={LINK.bookingChange} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/l/${LINK.bookingChange}/booking/change`));
  });
});
