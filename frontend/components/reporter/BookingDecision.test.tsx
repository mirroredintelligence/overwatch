import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOOKING_CHANGE_TOKEN, BOOKING_REQUEST_VIEW, csrfFor, LINK } from '@/test/fixtures/links';
import { resetLinkRequests, seenBffPosts, seenBffReads } from '@/test/msw/handlers/links';
import { BookingDecision } from './BookingDecision';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

// The service's booking request page (L02, W19; artboard B4). Sample values only: booking 4821, UCR West.

beforeEach(() => {
  resetLinkRequests();
  replace.mockClear();
});

async function openDecline() {
  await userEvent.click(await screen.findByRole('button', { name: 'Decline' }));
  return screen.findByRole('heading', { level: 1, name: 'Why can you not take this patient?' });
}

describe('BookingDecision: loading', () => {
  it('says "Opening your link." to a screen reader while the link is read, in the link frame', async () => {
    const { container } = render(<BookingDecision token={LINK.booking} />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening your link.');
    expect(container.querySelector('header')).toHaveTextContent('Overwatch');
    expect(container.querySelector('header')).toHaveTextContent('No login needed');
    await screen.findByRole('heading', { level: 1, name: 'UCR West' });
  });
});

describe('BookingDecision: an open request', () => {
  it('shows the reference, the service, the reply-by tag, the three facts and the note', async () => {
    const { container } = render(<BookingDecision token={LINK.booking} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Booking request 4821')).toBeInTheDocument();
    expect(screen.getByText('Reply by 14:26')).toBeInTheDocument();
    const facts = screen.getByText('Age band').closest('dl') as HTMLElement;
    expect(within(facts).getByText('80+')).toBeInTheDocument();
    expect(within(facts).getByText('Need')).toBeInTheDocument();
    expect(within(facts).getByText('Fall, no injury and frailty')).toBeInTheDocument();
    expect(within(facts).getByText('Wanted')).toBeInTheDocument();
    expect(within(facts).getByText('Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Referral details follow in SystmOne. No patient name is shown here.')).toBeInTheDocument();
    expect(screen.getByText('Opening this page booked nothing. It is booked when you press Confirm.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has Confirm as the one primary and Decline outlined, not a danger button', async () => {
    render(<BookingDecision token={LINK.booking} />);
    const confirm = await screen.findByRole('button', { name: 'Confirm booking' });
    const decline = screen.getByRole('button', { name: 'Decline' });
    expect(confirm.className).toMatch(/primary/);
    expect(decline.className).not.toMatch(/primary/);
    expect(decline.className).toMatch(/outline/);
  });

  it('posts nothing while it renders', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await screen.findByRole('heading', { level: 1, name: 'UCR West' });
    expect(seenBffPosts).toHaveLength(0);
  });

  it('confirms with the CSRF header and shows Booked with the reference, the time and the change link', async () => {
    const { container } = render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Booked' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([{ token: LINK.booking, body: { action: 'confirm' }, csrf: csrfFor(LINK.booking) }]);
    expect(screen.getByText('Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByText('Referral details follow in SystmOne.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Something changed?' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toHaveAttribute('href', 'tel:03001234567');
    expect(screen.getByRole('link', { name: 'Tell us something changed' })).toHaveAttribute(
      'href',
      `/l/${BOOKING_CHANGE_TOKEN}/booking/change`,
    );
    expect(screen.getByText('You can close this page.')).toBeInTheDocument();
    expect(container.querySelector('header')).not.toHaveTextContent('No login needed');
  });
});

describe('BookingDecision: declining opens the reason', () => {
  it('opens the reasons under Decline, posts nothing yet, and moves focus to the question', async () => {
    render(<BookingDecision token={LINK.booking} />);
    const heading = await openDecline();
    expect(heading).toHaveFocus();
    expect(screen.getByText('Optional. It helps the advisor choose again.')).toBeInTheDocument();
    expect(screen.getByText('Booking request 4821 · UCR West')).toBeInTheDocument();
    expect(screen.getByText('80+ · Fall, no injury and frailty · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('The advisor is told at once and will choose another service.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm booking' })).toBeNull();
    expect(seenBffPosts).toHaveLength(0);
  });

  it('declines with the chosen reason', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    await userEvent.click(screen.getByRole('radio', { name: 'Outside our criteria' }));
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([
      { token: LINK.booking, body: { action: 'decline', reason: 'outside-criteria' }, csrf: csrfFor(LINK.booking) },
    ]);
    expect(screen.getByText('Reference 4821 declined. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByText('Declined 14:19.')).toBeInTheDocument();
  });

  it('declines without a reason when none is chosen, and sends no reason field', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    await screen.findByRole('heading', { level: 1, name: 'Declined' });
    expect(seenBffPosts[0]?.body).toEqual({ action: 'decline' });
    expect(seenBffPosts[0]?.body).not.toHaveProperty('reason');
  });

  it('shows the four reasons as a radio group with the chosen one checked', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    expect(screen.getByRole('radiogroup', { name: 'Reason for declining' })).toBeInTheDocument();
    const full = screen.getByRole('radio', { name: 'We are full' });
    expect(full).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(full);
    expect(full).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Staffing or transport' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Other' })).toBeInTheDocument();
  });

  it('goes back to the request with Back to the request, and keeps the chosen reason', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    await userEvent.click(screen.getByRole('radio', { name: 'Other' }));
    await userEvent.click(screen.getByRole('button', { name: 'Back to the request' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toBeInTheDocument();
    await openDecline();
    expect(screen.getByRole('radio', { name: 'Other' })).toHaveAttribute('aria-checked', 'true');
    expect(seenBffPosts).toHaveLength(0);
  });

  it('keeps the data-el ids of the buttons and the reasons group', async () => {
    render(<BookingDecision token={LINK.booking} />);
    expect(await screen.findByRole('button', { name: 'Confirm booking' })).toHaveAttribute('data-el', 'SVC-BOOK-CONFIRM-BTN');
    expect(screen.getByRole('button', { name: 'Decline' })).toHaveAttribute('data-el', 'SVC-BOOK-DECLINE-BTN');
    await openDecline();
    expect(screen.getByRole('radiogroup')).toHaveAttribute('data-el', 'SVC-BOOK-REASONS');
    expect(screen.getByRole('button', { name: 'Decline booking' })).toHaveAttribute('data-el', 'SVC-BOOK-DECLINE-SEND-BTN');
  });

  it('is clean for axe with the reasons open', async () => {
    const { container } = render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('BookingDecision: closed and taken links', () => {
  it('shows the closed page when the link is closed on opening, and posts nothing', async () => {
    const { container } = render(<BookingDecision token={LINK.bookingDeclined} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This request has closed' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toHaveAttribute('href', 'tel:03001234567');
    expect(seenBffPosts).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the matching final page when the answer is refused as already declined (409)', async () => {
    render(<BookingDecision token={LINK.bookingTaken} />);
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([{ token: LINK.bookingTaken, body: { action: 'decline' }, csrf: csrfFor(LINK.bookingTaken) }]);
  });

  it('is clean for axe on the booked and declined pages', async () => {
    const { container, unmount } = render(<BookingDecision token={LINK.booking} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    await screen.findByRole('heading', { level: 1, name: 'Booked' });
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();
    const declined = render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
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

describe('BookingDecision: the times and the number (KI-648, KI-649, H-486, H-488)', () => {
  it('says when it was declined', async () => {
    render(<BookingDecision token={LINK.booking} />);
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(screen.getByText('Declined 14:19.')).toBeInTheDocument();
  });

  it('shows a closed request with its reference, when it closed and the coordination number', async () => {
    const { container } = render(<BookingDecision token={LINK.bookingExpired} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This request has closed' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821. Closed at 14:26.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toHaveAttribute('href', 'tel:03001234567');
    expect(container.querySelector('header')).not.toHaveTextContent('No login needed');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a request declined and then opened with the number, not a bare closed page', async () => {
    render(<BookingDecision token={LINK.bookingDeclined} />);
    expect(await screen.findByText('Reference 4821. Closed at 14:20.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toBeInTheDocument();
  });

  it('shows the time on the final page of an answer refused as already taken (409)', async () => {
    render(<BookingDecision token={LINK.bookingTaken} />);
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(screen.getByText('Declined 14:20.')).toBeInTheDocument();
  });

  it('says to phone the coordination team, with no number, for a closed link that carries none', async () => {
    render(<BookingDecision token={LINK.expired} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This request has closed' })).toBeInTheDocument();
    expect(screen.getByText('If you can still take this patient, phone the coordination team.')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('BookingDecision: a link read once (KI-651)', () => {
  const initial = { ...BOOKING_REQUEST_VIEW, csrfToken: csrfFor(LINK.booking), confirmedAt: null };

  it('shows a view it is given without reading the link again', async () => {
    render(<BookingDecision token={LINK.booking} initial={initial} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(seenBffReads).toEqual([]);
    expect(replace).not.toHaveBeenCalled();
  });

  it('answers with the CSRF token of the view it was given', async () => {
    render(<BookingDecision token={LINK.booking} initial={initial} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    await screen.findByRole('heading', { level: 1, name: 'Booked' });
    expect(seenBffPosts).toEqual([{ token: LINK.booking, body: { action: 'confirm' }, csrf: csrfFor(LINK.booking) }]);
    expect(seenBffReads).toEqual([]);
  });
});
