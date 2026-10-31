import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LINK, renewCsrfFor } from '@/test/fixtures/links';
import { resetLinkRequests } from '@/test/msw/handlers/links';
import { BookingChange } from './BookingChange';
import { BookingDecision } from './BookingDecision';
import { LinkExpired } from './LinkExpired';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

// Each result page opens with the round mark of the artboards: a tick for what went through, a dashed
// clock for what is closed. The page's heading says the same in words.

beforeEach(() => resetLinkRequests());

const CLOSED = {
  kind: 'booking' as const,
  reference: '4821',
  closedAt: '2026-10-23T13:26:00Z',
  confirmedAt: null,
  cancelledAt: null,
  coordinationPhone: '0300 123 4567',
};

function markOf(container: HTMLElement) {
  return container.querySelector('[data-tone]');
}

describe('result marks', () => {
  it('an expired link shows the closed mark', () => {
    const { container } = render(<LinkExpired token={LINK.expired} csrfToken={renewCsrfFor(LINK.expired)} />);
    expect(markOf(container)).toHaveAttribute('data-tone', 'closed');
  });

  it('a closed booking request shows the closed mark', () => {
    const { container } = render(<BookingDecision token={LINK.booking} initialClosed={{ ...CLOSED, state: 'expired' }} />);
    expect(screen.getByRole('heading', { level: 1, name: 'This request has closed' })).toBeInTheDocument();
    expect(markOf(container)).toHaveAttribute('data-tone', 'closed');
  });

  it('a withdrawn booking shows the closed mark, and a booking cancelled by the coordination team too', () => {
    const withdrawn = render(<BookingChange token={LINK.bookingChange} initialClosed={{ ...CLOSED, state: 'withdrawn' }} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Withdrawn' })).toBeInTheDocument();
    expect(markOf(withdrawn.container)).toHaveAttribute('data-tone', 'closed');
    withdrawn.unmount();
    const cancelled = render(<BookingChange token={LINK.bookingChange} initialClosed={{ ...CLOSED, state: 'cancelled', cancelledAt: '2026-10-23T13:40:00Z' }} />);
    expect(markOf(cancelled.container)).toHaveAttribute('data-tone', 'closed');
  });

  it('a patient reported not reached shows the done mark under Thank you', () => {
    const { container } = render(<BookingChange token={LINK.bookingChange} initialClosed={{ ...CLOSED, state: 'not-reached' }} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Thank you' })).toBeInTheDocument();
    expect(markOf(container)).toHaveAttribute('data-tone', 'done');
  });
});
