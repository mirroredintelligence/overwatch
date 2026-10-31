import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BookingState } from '@/lib/advisor/bookings';
import { runAxe } from '@/test/a11y';
import {
  SERVICE_PHONE,
  STATE_CONFIRMED,
  STATE_DECLINED,
  STATE_DECLINED_NO_REASON,
  STATE_EXPIRED,
  STATE_REQUESTED,
  STATE_REQUESTED_TENANT_POLICY,
  STATE_WITHDRAWN,
  STATE_WITHDRAWN_ACKNOWLEDGED,
} from '@/test/fixtures/bookings';
import { BookingCard } from './BookingCard';

// The advisor's booking card (W20): the live states of one request or booking. Sample values only.
// Times are 30 October 2026, GMT. The card's clock is the test's fake clock.

const SERVICE = 'UCR West';

function renderCard(booking: BookingState, extra: Partial<React.ComponentProps<typeof BookingCard>> = {}) {
  return render(
    <BookingCard booking={booking} serviceName={SERVICE} servicePhone={SERVICE_PHONE} now={() => Date.parse('2026-10-30T14:16:30Z')} {...extra} />,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date('2026-10-30T14:16:30Z') });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('BookingCard: requested', () => {
  it('shows the requested text, the times and the pending count, and is clean for axe', async () => {
    const { container } = renderCard(STATE_REQUESTED);
    expect(screen.getByText('Requested')).toBeInTheDocument();
    expect(screen.getByText('Not booked yet')).toBeInTheDocument();
    expect(screen.getByText('Text delivered 14:16. Waiting for CONFIRMED. Phone prompt at 14:21. Request expires 14:26.')).toBeInTheDocument();
    expect(screen.getByText('Colleagues see 1 pending on the board.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Phone them instead' })).toHaveAttribute('data-el', 'ADV-BOOK-PHONE-BTN');
    expect(screen.getByRole('button', { name: 'Cancel request' })).toHaveAttribute('data-el', 'ADV-BOOK-CANCEL-BTN');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the service phone as a tel link once it is asked for', async () => {
    renderCard(STATE_REQUESTED);
    await userEvent.click(screen.getByRole('button', { name: 'Phone them instead' }));
    expect(screen.getByRole('link', { name: SERVICE_PHONE })).toHaveAttribute('href', 'tel:0300 123 4567');
  });

  it('opens the cancel dialog for a request, and cancels only when a reason is chosen and confirmed', async () => {
    const onCancelBooking = vi.fn();
    renderCard(STATE_REQUESTED, { onCancelBooking });
    await userEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    expect(screen.getByRole('dialog', { name: 'Cancel request' })).toBeInTheDocument();
    expect(onCancelBooking).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Caller declined' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    expect(onCancelBooking).toHaveBeenCalledWith('caller-declined');
  });

  it('says so with an alert at the phone prompt time, and not before', () => {
    renderCard(STATE_REQUESTED, { now: () => Date.parse('2026-10-30T14:20:59Z') });
    expect(screen.queryByRole('alert')).toBeNull();
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(screen.getByRole('alert')).toHaveTextContent('No reply yet. Phone UCR West now.');
  });

  it('shows the phone prompt alert at once when the prompt time has passed', () => {
    renderCard(STATE_REQUESTED, { now: () => Date.parse('2026-10-30T14:25:00Z') });
    expect(screen.getByRole('alert')).toHaveTextContent('No reply yet. Phone UCR West now.');
  });

  it('does not show the phone prompt alert once the booking is confirmed', () => {
    renderCard(STATE_CONFIRMED, { now: () => Date.parse('2026-10-30T14:25:00Z') });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('clears its timer when it unmounts', () => {
    const { unmount } = renderCard(STATE_REQUESTED, { now: () => Date.parse('2026-10-30T14:16:30Z') });
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('BookingCard: booked', () => {
  it('shows Booked, the confirmation time and the next step, with the summary and outcome buttons', async () => {
    const { container } = renderCard(STATE_CONFIRMED);
    expect(screen.getByText('Booked')).toBeInTheDocument();
    expect(screen.getByText('Confirmed 14:19')).toBeInTheDocument();
    expect(screen.getByText('Reference 4821. Capacity reduced by 1. Next: complete the referral in SystmOne.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy summary for SystmOne' })).toHaveAttribute('data-el', 'ADV-BOOK-NEXT-BTN');
    expect(screen.getByRole('button', { name: 'Record outcome' })).toHaveAttribute('data-el', 'ADV-BOOK-OUTCOME-BTN');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('BookingCard: declined', () => {
  it('says why, with the reason in words and the two ways on', async () => {
    const { container } = renderCard(STATE_DECLINED, { onBackToOptions: vi.fn() });
    expect(screen.getByText('Declined')).toBeInTheDocument();
    expect(screen.getByText('Not booked')).toBeInTheDocument();
    expect(
      screen.getByText('Declined 14:19. Reason: outside criteria. Pending count released. Choose another option or phone to discuss.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back to options' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Phone to discuss' })).toHaveAttribute('href', 'tel:0300 123 4567');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says the reason was not given when the service gave none', () => {
    renderCard(STATE_DECLINED_NO_REASON);
    expect(screen.getByText('Declined 14:19. Reason: not given. Pending count released. Choose another option or phone to discuss.')).toBeInTheDocument();
  });

  it('calls onBackToOptions from Back to options', async () => {
    const onBackToOptions = vi.fn();
    renderCard(STATE_DECLINED, { onBackToOptions });
    await userEvent.click(screen.getByRole('button', { name: 'Back to options' }));
    expect(onBackToOptions).toHaveBeenCalledTimes(1);
  });
});

describe('BookingCard: no reply', () => {
  it('says the request expired, that nothing is booked, and that it cannot be assumed accepted', async () => {
    const { container } = renderCard(STATE_EXPIRED);
    expect(screen.getByText('No reply')).toBeInTheDocument();
    expect(screen.getByText('Not booked. Phone now.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'No reply after 5 min, so you were prompted to phone. The request expired at 10 min and the pending count is released. Do not assume it was accepted.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Phone UCR West' })).toHaveAttribute('href', 'tel:0300 123 4567');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('calls onNextOption from Try next option', async () => {
    const onNextOption = vi.fn();
    renderCard(STATE_EXPIRED, { onNextOption });
    await userEvent.click(screen.getByRole('button', { name: 'Try next option' }));
    expect(onNextOption).toHaveBeenCalledTimes(1);
  });
});

describe('BookingCard: live region', () => {
  it('announces a change of status once, politely, and not on first render', () => {
    const { rerender } = renderCard(STATE_REQUESTED);
    const region = screen.getByRole('status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveTextContent('');
    rerender(<BookingCard booking={STATE_CONFIRMED} serviceName={SERVICE} servicePhone={SERVICE_PHONE} now={() => Date.parse('2026-10-30T14:19:30Z')} />);
    expect(screen.getByRole('status')).toHaveTextContent('UCR West confirmed booking 4821');
  });
});

describe('BookingCard: a service whose phone number is not on this screen (H-530)', () => {
  const NO_NUMBER = 'This service\'s phone number is not on this screen. Find it in your service directory.';

  it('says so, in place of a number, when "Phone them instead" is pressed', async () => {
    render(<BookingCard booking={STATE_REQUESTED} serviceName="UCR West" servicePhone={null} now={() => Date.parse('2026-10-30T14:16:30Z')} />);
    await userEvent.click(screen.getByRole('button', { name: 'Phone them instead' }));

    expect(screen.getByText(NO_NUMBER)).toBeInTheDocument();
  });

  it('says so on the no-reply card, where the way on is to phone', () => {
    render(<BookingCard booking={STATE_EXPIRED} serviceName="UCR West" servicePhone={null} />);

    expect(screen.getByText(NO_NUMBER)).toBeInTheDocument();
  });

  it('says so on the declined card', () => {
    render(<BookingCard booking={STATE_DECLINED} serviceName="UCR West" servicePhone={null} />);

    expect(screen.getByText(NO_NUMBER)).toBeInTheDocument();
  });
});


describe('BookingCard: the request text is not said to have arrived unless it did (H-494)', () => {
  it.each([
    ['queued', 'Text waiting to be sent 14:16.'],
    ['sent', 'Text sent 14:16.'],
    ['delivered', 'Text delivered 14:16.'],
  ] as const)('says %s', (delivery, words) => {
    renderCard({ ...STATE_REQUESTED, delivery });
    expect(screen.getByText(new RegExp(`^${words.replace('.', '\\.')} Waiting for CONFIRMED`))).toBeInTheDocument();
  });

  it('says the text did not arrive, and to phone, at once and not only at the prompt time', () => {
    renderCard({ ...STATE_REQUESTED, delivery: 'failed' });
    expect(screen.getByText(/^Text not delivered 14:16\./)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('The text to UCR West was not delivered. Phone them now.');
  });

  it('says only "Text sent" for a booking from before the state was kept', () => {
    renderCard({ ...STATE_REQUESTED, delivery: null });
    expect(screen.getByText(/^Text sent 14:16\./)).toBeInTheDocument();
  });
});

describe('BookingCard: the tenant\'s own phone prompt and reply times (H-493)', () => {
  it('says the prompt and expiry the booking carries, not the defaults', () => {
    renderCard(STATE_REQUESTED_TENANT_POLICY);
    expect(screen.getByText(/Phone prompt at 14:19\. Request expires 14:24\./)).toBeInTheDocument();
  });

  it('says the minutes of the booking on the no-reply card', () => {
    renderCard({ ...STATE_REQUESTED_TENANT_POLICY, status: 'expired', expiredAt: '2026-10-30T14:24:00Z' });
    expect(
      screen.getByText(
        'No reply after 3 min, so you were prompted to phone. The request expired at 8 min and the pending count is released. Do not assume it was accepted.',
      ),
    ).toBeInTheDocument();
  });
});

describe('BookingCard: a withdrawal already answered (KI-451)', () => {
  it('opens the alert for a withdrawal nobody has answered', () => {
    renderCard(STATE_WITHDRAWN);
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('does not open the alert again after a reload, when the back end holds the answer', () => {
    renderCard(STATE_WITHDRAWN_ACKNOWLEDGED);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.queryByText(/This is not answered yet/)).toBeNull();
    expect(screen.getByText('Withdrawn. Alert answered at 14:43.')).toBeInTheDocument();
  });
});
