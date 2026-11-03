'use client';

import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { type BookingStream, type BookingFetch, useBooking } from '@/lib/advisor/useBooking';
import styles from './Advisor.module.css';
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
  /** The two next steps of a confirmed booking card: record the outcome, and copy the summary. */
  onRecordOutcome?: () => void;
  onCopySummary?: () => void;
  /** The request stage (one option has the room): "Back to options" sits beside the request control until a request exists. */
  backToOptions?: boolean;
};

export function BookingPanel(props: BookingPanelProps) {
  const { caseRef, serviceId, serviceName, servicePhone, openStream, fetcher, now, onSeeOptions, onAskClinical, onRecordOutcome, onCopySummary, backToOptions = false } = props;
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
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="ADV-OPT-REQUEST-BTN" onClick={() => void request()}>
          Request booking
        </Button>
        {backToOptions ? (
          <Button variant="neutral" dataEl="ADV-OPT-BACK-BTN" onClick={() => onSeeOptions?.()}>
            Back to options
          </Button>
        ) : null}
      </div>
      {conflict ? <Banner tone="warning" title={`${serviceName} already has a request waiting. Phone them instead.`} dataEl="ADV-BOOK-CONFLICT" /> : null}
      {failed ? <Banner tone="warning" title="We could not send the request. Try again." dataEl="ADV-BOOK-FAILED" /> : null}
    </div>
  );
}
