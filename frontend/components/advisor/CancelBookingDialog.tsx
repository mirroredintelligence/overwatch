'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { CANCEL_REASONS, type CancelReason } from '@/lib/advisor/bookings';
import styles from './Advisor.module.css';

// The advisor's dialog to cancel a booking, or a request not yet answered (W21). It takes focus when it
// opens and gives it back to the control that opened it when it closes. Cancel stays off until a reason
// is chosen. The service is told by its own channel; this page does not message it.

export type CancelBookingDialogProps = {
  kind: 'booking' | 'request';
  serviceName: string;
  /** The message to show when the booking moved on before the cancel. */
  conflict?: string | null;
  busy?: boolean;
  onConfirm: (reason: CancelReason) => void;
  onKeep: () => void;
};

export function CancelBookingDialog({ kind, serviceName, conflict = null, busy = false, onConfirm, onKeep }: CancelBookingDialogProps) {
  const [reason, setReason] = useState<CancelReason | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus();
    return () => opener?.focus();
  }, []);

  const request = kind === 'request';
  const title = request ? 'Cancel request' : 'Cancel booking';

  return (
    <section role="dialog" aria-modal="true" aria-labelledby={headingId} className={styles.dialog} data-el="ADV-CANCEL-DIALOG">
      <h2 id={headingId} ref={headingRef} tabIndex={-1} className={styles.heading}>
        {title}
      </h2>
      <p className={styles.text}>{request ? `Cancel the request to ${serviceName}?` : `Cancel the booking with ${serviceName}?`}</p>
      <div role="group" aria-label={request ? 'Why cancel the request?' : 'Why cancel the booking?'} className={styles.actions}>
        {CANCEL_REASONS.map((option) => (
          <OptionButton key={option.code} selected={reason === option.code} dataEl={option.dataEl} onSelect={() => setReason(option.code)}>
            {option.label}
          </OptionButton>
        ))}
      </div>
      <p className={styles.text}>The service is told by its own channel. The slot goes back to available.</p>
      {conflict !== null ? <Banner tone="warning" title={conflict} /> : null}
      <div className={styles.actions}>
        <Button
          variant="primary"
          busy={busy}
          disabled={reason === null}
          dataEl="ADV-CANCEL-CONFIRM-BTN"
          onClick={() => reason !== null && onConfirm(reason)}
        >
          {title}
        </Button>
        <Button variant="neutral" dataEl="ADV-CANCEL-KEEP-BTN" onClick={onKeep}>
          {request ? 'Keep request' : 'Keep booking'}
        </Button>
      </div>
    </section>
  );
}
