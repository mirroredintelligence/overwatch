import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { STATE_WITHDRAWN } from '@/test/fixtures/bookings';
import { openAlerts, resetBookingRequests } from '@/test/msw/handlers/bookings';
import AdvisorLayout from './layout';

// Every advisor page carries the strip of open booking alerts above its own content (H-496).

beforeEach(() => {
  resetBookingRequests();
});

describe('the advisor layout', () => {
  it('shows the page it wraps', () => {
    render(
      <AdvisorLayout>
        <p>the page</p>
      </AdvisorLayout>,
    );
    expect(screen.getByText('the page')).toBeInTheDocument();
  });

  it('puts an unanswered withdrawal above the page, so an advisor on any page sees it', async () => {
    openAlerts.current = [STATE_WITHDRAWN];
    render(
      <AdvisorLayout>
        <p>the page</p>
      </AdvisorLayout>,
    );
    const alert = await screen.findByRole('alert');
    const page = screen.getByText('the page');
    expect(alert.compareDocumentPosition(page) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
