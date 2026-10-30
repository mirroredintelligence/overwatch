'use client';

import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { type BookingStream, type BookingFetch, useBooking } from '@/lib/advisor/useBooking';
import { BookingCard } from './BookingCard';

// The "Request booking" control for one service on the options screen, and the card it leaves behind
// (W20). The options list (W13) mounts one of these per service. Pressing the control posts once.

export type BookingPanelProps = {
  caseRef: string;
  serviceId: string;
  serviceName: string;
  servicePhone: string | null;
  /** Opens the live stream once a booking exists. Defaults to none. */
  openStream?: () => BookingStream | null;
  fetcher?: BookingFetch;
  now?: () => number;
};

export function BookingPanel(props: BookingPanelProps) {
  const { caseRef, serviceId, serviceName, servicePhone, openStream, fetcher, now } = props;
  const { booking, busy, conflict, failed, request } = useBooking({ caseRef, serviceId, openStream, fetcher });

  if (booking !== null) {
    return <BookingCard booking={booking} serviceName={serviceName} servicePhone={servicePhone} now={now} />;
  }

  return (
    <div>
      <Button variant="primary" busy={busy} dataEl="ADV-OPT-REQUEST-BTN" onClick={() => void request()}>
        Request booking
      </Button>
      {conflict ? <Banner tone="warning" title={`${serviceName} already has a request waiting. Phone them instead.`} dataEl="ADV-BOOK-CONFLICT" /> : null}
      {failed ? <Banner tone="warning" title="We could not send the request. Try again." dataEl="ADV-BOOK-FAILED" /> : null}
    </div>
  );
}
