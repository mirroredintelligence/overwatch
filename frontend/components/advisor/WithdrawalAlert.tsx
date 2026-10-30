'use client';

import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { clock, type BookingState, withdrawReasonWording } from '@/lib/advisor/bookings';
import styles from './Advisor.module.css';

// The alert an advisor gets when a service withdraws a confirmed booking, or reports the patient not
// reached (W21). It is the shared dialog shell (W14) as an alert dialog.
//
// DEC-854: the alert is acknowledged ONLY by an explicit answer, "I have phoned the caller" or "The
// caller is already being helped". Acknowledging stops the shift lead's escalation (R17), and a
// withdrawn booking leaves a patient's referral with nowhere to go, so no other control and no key does
// it: "See options again", "Ask a clinical advisor" and Escape leave the alert open and the escalation
// running. The card then keeps a standing notice until it is answered.

export type WithdrawalAlertProps = {
  booking: BookingState;
  serviceName: string;
  /** Sends the acknowledgement. True when the back end took it, false when it did not. */
  onAcknowledge: () => Promise<boolean>;
  /** The alert was set aside without an answer (another control, or Escape). Nothing is acknowledged. */
  onLeaveOpen: () => void;
  onSeeOptions: () => void;
  onAskClinical?: () => void;
};

const SEND_FAILED = 'The answer could not be sent. The shift lead will still be told. Try again.';

export function WithdrawalAlert({ booking, serviceName, onAcknowledge, onLeaveOpen, onSeeOptions, onAskClinical }: WithdrawalAlertProps) {
  const [failed, setFailed] = useState(false);
  const sending = useRef(false);

  const notReached = booking.status === 'not-reached';
  const title = notReached ? `${serviceName} could not reach the patient` : `${serviceName} withdrew`;
  const reason = booking.withdrawReason === null ? 'not given' : withdrawReasonWording(booking.withdrawReason);
  const when = booking.withdrawnAt === null ? '' : clock(booking.withdrawnAt);

  async function answer() {
    if (sending.current) return;
    sending.current = true;
    setFailed(false);
    try {
      if (!(await onAcknowledge())) setFailed(true);
    } finally {
      sending.current = false;
    }
  }

  return (
    <Dialog title={title} role="alertdialog" focusFirst={false} dataEl="ADV-WITHDRAWN-ALERT" onClose={onLeaveOpen}>
      <p className={styles.badge}>
        <span>{notReached ? 'Not reached' : 'Withdrawn'}</span>
      </p>
      <h3 className={styles.heading}>{notReached ? 'The patient could not be reached' : `${serviceName} can no longer take this patient`}</h3>
      <p className={styles.text}>{notReached ? `Reason: ${reason}. Reported ${when}.` : `Reason: ${reason}. Withdrawn ${when}.`}</p>
      {notReached ? (
        <p className={styles.text}>The coordination team is told and will phone the caller.</p>
      ) : (
        <>
          <p className={styles.text}>Phone the caller now.</p>
          <p className={styles.text}>Tell them another service is being found.</p>
          <p className={styles.text}>If nobody acts within 10 minutes the shift lead is alerted.</p>
        </>
      )}
      {failed ? (
        <p role="alert" className={styles.text}>
          {SEND_FAILED}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" dataEl="ADV-WITHDRAWN-PHONED-BTN" onClick={() => void answer()}>
          I have phoned the caller
        </Button>
        <Button variant="secondary" dataEl="ADV-WITHDRAWN-HELPED-BTN" onClick={() => void answer()}>
          The caller is already being helped
        </Button>
      </div>
      <div className={styles.actions}>
        <Button
          variant="neutral"
          dataEl="ADV-WITHDRAWN-OPTIONS-BTN"
          onClick={() => {
            onSeeOptions();
            onLeaveOpen();
          }}
        >
          See options again
        </Button>
        {notReached ? null : (
          <Button
            variant="neutral"
            dataEl="ADV-WITHDRAWN-CLINICAL-BTN"
            onClick={() => {
              onAskClinical?.();
              onLeaveOpen();
            }}
          >
            Ask a clinical advisor
          </Button>
        )}
      </div>
    </Dialog>
  );
}
