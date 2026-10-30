import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { csrfFor, LINK } from '@/test/fixtures/links';
import { resetLinkRequests, seenBffPosts } from '@/test/msw/handlers/links';
import { BookingChange } from './BookingChange';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

// The service's change page for a confirmed booking (L02, W22). Sample values only: booking 4821.

beforeEach(() => {
  resetLinkRequests();
  replace.mockClear();
});

describe('BookingChange: the booked view', () => {
  it('shows the booking, its rows and the two ways to change it, and posts nothing', async () => {
    const { container } = render(<BookingChange token={LINK.bookingChange} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Booking 4821')).toBeInTheDocument();
    expect(screen.getByText('Booked')).toBeInTheDocument();
    expect(screen.getByText('Referral details follow in SystmOne.')).toBeInTheDocument();
    expect(screen.getByText('Age band 80+')).toBeInTheDocument();
    expect(screen.getByText('Wanted Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Something changed? Tell us here so the coordination team can act at once.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'We cannot take this patient now' })).toHaveAttribute('data-el', 'SVC-CHANGE-WITHDRAW-BTN');
    expect(screen.getByRole('button', { name: 'Patient not found or not there' })).toHaveAttribute('data-el', 'SVC-CHANGE-NOTREACHED-BTN');
    expect(seenBffPosts).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('BookingChange: withdrawing', () => {
  it('keeps Withdraw booking disabled until a reason is chosen', async () => {
    render(<BookingChange token={LINK.bookingChange} />);
    await userEvent.click(await screen.findByRole('button', { name: 'We cannot take this patient now' }));
    expect(screen.getByRole('heading', { level: 2, name: 'Why can you no longer take this patient?' })).toBeInTheDocument();
    expect(screen.getByText('The coordination team is told at once and will find another service. The patient will not be left without a plan.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Withdraw booking' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Withdraw booking' })).toHaveAttribute('data-el', 'SVC-WITHDRAW-SUBMIT-BTN');
    expect(seenBffPosts).toHaveLength(0);
  });

  it('withdraws for staffing with the CSRF header and shows Withdrawn with the coordination team number', async () => {
    const { container } = render(<BookingChange token={LINK.bookingChange} />);
    await userEvent.click(await screen.findByRole('button', { name: 'We cannot take this patient now' }));
    await userEvent.click(screen.getByRole('button', { name: 'Staffing' }));
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Withdrawn' })).toBeInTheDocument();
    expect(seenBffPosts).toEqual([
      { token: LINK.bookingChange, body: { action: 'withdraw', reason: 'staffing' }, csrf: csrfFor(LINK.bookingChange) },
    ]);
    expect(screen.getByText('The coordination team has been told and is finding another service.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 123 4567' })).toHaveAttribute('href', 'tel:0300 123 4567');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('goes back to the booked view with Back, without posting', async () => {
    render(<BookingChange token={LINK.bookingChange} />);
    await userEvent.click(await screen.findByRole('button', { name: 'We cannot take this patient now' }));
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Something changed? Tell us here so the coordination team can act at once.')).toBeInTheDocument();
    expect(seenBffPosts).toHaveLength(0);
  });

  it('shows the withdrawn view when the withdrawal is refused as already changed (409)', async () => {
    render(<BookingChange token={LINK.bookingChangeTaken} />);
    await userEvent.click(await screen.findByRole('button', { name: 'We cannot take this patient now' }));
    await userEvent.click(screen.getByRole('button', { name: 'Other' }));
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Withdrawn' })).toBeInTheDocument();
  });
});

describe('BookingChange: patient not reached', () => {
  it('saves a not-reached report with its reason, then thanks the service', async () => {
    const { container } = render(<BookingChange token={LINK.bookingChange} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Patient not found or not there' }));
    expect(screen.getByRole('heading', { level: 2, name: 'Patient not found or not there' })).toBeInTheDocument();
    expect(screen.getByText('The coordination team is told and will phone the caller.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('data-el', 'SVC-NOTREACHED-SAVE-BTN');
    await userEvent.click(screen.getByRole('button', { name: 'No answer at the door' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Thank you' })).toBeInTheDocument();
    expect(screen.getByText('The coordination team has been told.')).toBeInTheDocument();
    expect(seenBffPosts).toEqual([
      { token: LINK.bookingChange, body: { action: 'not-reached', reason: 'no-answer' }, csrf: csrfFor(LINK.bookingChange) },
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('offers the four not-reached reasons', async () => {
    render(<BookingChange token={LINK.bookingChange} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Patient not found or not there' }));
    for (const name of ['Not at the address', 'No answer at the door', 'Gone to hospital', 'Other']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  });
});

describe('BookingChange: a booking the coordination team cancelled', () => {
  it('shows the cancelled view with no action needed, and posts nothing', async () => {
    const { container } = render(<BookingChange token={LINK.bookingCancelled} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Cancelled by the coordination team' })).toBeInTheDocument();
    expect(screen.getByText('The booking was cancelled by the coordination team. No action needed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(seenBffPosts).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('BookingChange: links that are not change links', () => {
  it('shows the closed page for a link that has closed (a change link older than 24 hours)', async () => {
    render(<BookingChange token={LINK.expired} />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This link has closed' })).toBeInTheDocument();
    expect(screen.getByText('You can close this page.')).toBeInTheDocument();
  });

  it('sends a booking request to its own page', async () => {
    render(<BookingChange token={LINK.booking} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/l/${LINK.booking}/booking`));
  });
});

describe('BookingChange: close', () => {
  it('says the page can be closed, and does not navigate', async () => {
    render(<BookingChange token={LINK.bookingChange} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Close' }));
    expect(screen.getByText('You can close this page.')).toBeInTheDocument();
  });
});
