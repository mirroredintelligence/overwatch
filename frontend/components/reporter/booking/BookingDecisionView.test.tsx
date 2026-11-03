import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BookingDecisionView, type BookingDecisionViewProps, type BookingScreen } from './BookingDecisionView';

// The one view of a booking request (artboard B4, shared states St). Sample values only: booking 4821, UCR West.

const REQUEST: BookingScreen = {
  kind: 'request',
  reference: '4821',
  service: 'UCR West',
  ageBand: '80+',
  need: 'Fall and frailty',
  urgency: 'Within 2 hrs',
  replyBy: '14:26',
  onlyService: false,
  confirmLabel: 'Confirm booking',
  note: 'The referral follows elsewhere.',
};

function show(screenState: BookingScreen, over: Partial<BookingDecisionViewProps> = {}) {
  const onConfirm = vi.fn();
  const onDecline = vi.fn();
  const view = render(
    <BookingDecisionView screen={screenState} phone="0300 000 0000" dataElPrefix="T-BOOK" onConfirm={onConfirm} onDecline={onDecline} {...over} />,
  );
  return { ...view, onConfirm, onDecline };
}

describe('BookingDecisionView', () => {
  it('shows a loading state that is spoken and has no heading', () => {
    show({ kind: 'loading', label: 'Opening your link.' });
    expect(screen.getByRole('status')).toHaveTextContent('Opening your link.');
    expect(screen.queryByRole('heading')).toBeNull();
  });

  it('shows the request with Confirm as the only primary and calls onConfirm', async () => {
    const { onConfirm, container } = show(REQUEST);
    expect(screen.getByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('The referral follows elsewhere.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm booking' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('opens the reasons on Decline, calls onDecline with the reason only on Decline booking', async () => {
    const { onDecline } = show(REQUEST);
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }));
    expect(onDecline).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('radio', { name: 'We are full' }));
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(onDecline).toHaveBeenCalledWith('full');
  });

  it('calls onDecline with null when no reason is chosen', async () => {
    const { onDecline } = show(REQUEST);
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }));
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(onDecline).toHaveBeenCalledWith(null);
  });

  it('moves the choice with the arrow keys in the reasons', async () => {
    show(REQUEST);
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }));
    await userEvent.click(screen.getByRole('radio', { name: 'We are full' }));
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Outside our criteria' })).toHaveAttribute('aria-checked', 'true');
  });

  it('waits on every button while busy', async () => {
    show(REQUEST, { busy: true });
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled();
  });

  it('shows a notice beside the request, announced', () => {
    show(REQUEST, { notice: { tone: 'warning', text: 'Too many tries.' } });
    expect(screen.getByRole('status')).toHaveTextContent('Too many tries.');
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toBeEnabled();
  });

  it('shows booked, declined and closed with their marks and no buttons', () => {
    const booked = show({ kind: 'booked', reference: '4821', service: 'UCR West', confirmedAt: null, note: 'Later.', changeHref: null });
    expect(screen.getByText('Reference 4821, UCR West. The advisor has been told.')).toBeInTheDocument();
    expect(booked.container.querySelector('[data-tone="done"]')).not.toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    booked.unmount();
    const declined = show({ kind: 'declined', reference: '4821', declinedAt: null });
    expect(screen.getByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(declined.container.querySelector('[data-tone="closed"]')).not.toBeNull();
    declined.unmount();
    const closed = show({ kind: 'closed', heading: 'This request has closed', detail: null, phoneAsk: true }, { phone: null });
    expect(screen.getByText('If you can still take this patient, phone the coordination team.')).toBeInTheDocument();
    expect(closed.container.querySelector('[data-tone="closed"]')).not.toBeNull();
  });

  it('shows a failure in plain words as an alert', () => {
    show({ kind: 'failed', lead: 'We could not load this booking.', text: 'Try again shortly.' });
    expect(screen.getByRole('alert')).toHaveTextContent('We could not load this booking. Try again shortly.');
  });
});
