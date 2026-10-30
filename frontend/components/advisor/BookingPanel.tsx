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
  /** Back to the options list: after a cancel, a decline, an expiry or a withdrawal acknowledged. */
  onSeeOptions?: () => void;
  onAskClinical?: () => void;
  /** "Record outcome" and "Copy summary for SystmOne" on a confirmed booking. */
  onRecordOutcome?: () => void;
  onCopySummary?: () => void;
};

export function BookingPanel(props: BookingPanelProps) {
  const { caseRef, serviceId, serviceName, servicePhone, openStream, fetcher, now, onSeeOptions, onAskClinical, onRecordOutcome, onCopySummary } = props;
  const { booking, busy, conflict, failed, request, cancelBusy, cancelConflict, cancel, acknowledge } = useBooking({
    caseRef,
    serviceId,
    openStream,
    fetcher,
  });

  if (booking !== null) {
    return (
      <BookingCard
        booking={booking}
        serviceName={serviceName}
        servicePhone={servicePhone}
        now={now}
        cancelBusy={cancelBusy}
        cancelConflict={cancelConflict}
        onCancelBooking={(reason) => void cancel(reason)}
        onAcknowledge={acknowledge}
        onSeeOptions={onSeeOptions}
        onBackToOptions={onSeeOptions}
        onNextOption={onSeeOptions}
        onAskClinical={onAskClinical}
        onRecordOutcome={onRecordOutcome}
        onCopySummary={onCopySummary}
      />
    );
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
