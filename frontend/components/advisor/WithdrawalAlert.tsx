'use client';

import { useEffect, useRef } from 'react';
import { Button } from '@/components/ui/Button';
import { clock, type BookingState, withdrawReasonWording } from '@/lib/advisor/bookings';
import styles from './Advisor.module.css';

// The alert an advisor gets when a service withdraws a confirmed booking, or reports the patient not
// reached (W21). It is an alert dialog and takes focus when it opens. Any action first acknowledges
// the alert, so the shift lead's escalation stops; the action then happens.

export type WithdrawalAlertProps = {
  booking: BookingState;
  serviceName: string;
  onAcknowledge: () => Promise<void>;
  onSeeOptions: () => void;
  onAskClinical?: () => void;
  onPhoneCaller?: () => void;
};

export function WithdrawalAlert({ booking, serviceName, onAcknowledge, onSeeOptions, onAskClinical, onPhoneCaller }: WithdrawalAlertProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const notReached = booking.status === 'not-reached';
  const title = notReached ? `${serviceName} could not reach the patient` : `${serviceName} withdrew`;
  const reason = booking.withdrawReason === null ? 'not given' : withdrawReasonWording(booking.withdrawReason);
  const when = booking.withdrawnAt === null ? '' : clock(booking.withdrawnAt);

  async function act(next?: () => void) {
    await onAcknowledge();
    next?.();
  }

  return (
    <section role="alertdialog" aria-labelledby="withdrawal-title" aria-modal="true" className={styles.dialog} data-el="ADV-WITHDRAWN-ALERT">
      <h2 id="withdrawal-title" className={styles.heading}>
        {title}
      </h2>
      <p className={styles.badge}>
        <span>{notReached ? 'Not reached' : 'Withdrawn'}</span>
      </p>
      <h3 ref={headingRef} tabIndex={-1} className={styles.heading}>
        {notReached ? 'The patient could not be reached' : `${serviceName} can no longer take this patient`}
      </h3>
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
      <div className={styles.actions}>
        <Button variant="primary" dataEl="ADV-WITHDRAWN-OPTIONS-BTN" onClick={() => void act(onSeeOptions)}>
          See options again
        </Button>
        {notReached ? null : (
          <Button variant="secondary" dataEl="ADV-WITHDRAWN-CLINICAL-BTN" onClick={() => void act(onAskClinical)}>
            Ask a clinical advisor
          </Button>
        )}
        <Button variant="neutral" dataEl="ADV-WITHDRAWN-CALLER-BTN" onClick={() => void act(onPhoneCaller)}>
          Phone the caller
        </Button>
      </div>
    </section>
  );
}
