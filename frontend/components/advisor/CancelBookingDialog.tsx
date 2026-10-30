'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { OptionButton } from '@/components/ui/OptionButton';
import { CANCEL_REASONS, type CancelReason } from '@/lib/advisor/bookings';
import styles from './Advisor.module.css';

// The advisor's dialog to cancel a booking, or a request not yet answered (W21). It is the shared
// dialog shell (W14): focus moves in on open and back to the control that opened it on close, Escape
// keeps the booking, Tab stays inside. Cancel stays off until a reason is chosen. The service is told by
// its own channel; this page does not message it.

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
  const request = kind === 'request';
  const title = request ? 'Cancel request' : 'Cancel booking';

  return (
    <Dialog title={title} dataEl="ADV-CANCEL-DIALOG" onClose={onKeep}>
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
    </Dialog>
  );
}
