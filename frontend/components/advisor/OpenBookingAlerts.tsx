'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { type BookingState, parseBookingList } from '@/lib/advisor/bookings';
import styles from './OpenBookingAlerts.module.css';

// The strip of open booking alerts, above every advisor page (H-496, DEC-854). A withdrawal or a
// not-reached report stays open until an advisor answers it on the booking card, and the advisor who gets
// it may not be on that card (another case, the home page, the board). This reads the back end's open
// alerts and names each with the way to its case. It answers nothing: the answer is given on the card,
// where the caller's case is. A read that fails says so, and keeps what was shown: nothing shown must
// never read as "everything answered".

export const ALERT_POLL_MS = 30_000;

export type OpenBookingAlertsProps = {
  /** How often the alerts are read again (ms). */
  pollMs?: number;
};

export function OpenBookingAlerts({ pollMs = ALERT_POLL_MS }: OpenBookingAlertsProps) {
  const [alerts, setAlerts] = useState<readonly BookingState[]>([]);
  const [unread, setUnread] = useState(false);

  useEffect(() => {
    let stale = false;
    async function read() {
      try {
        const response = await fetch('/api/bff/bookings?alert=open', { method: 'GET', cache: 'no-store', credentials: 'same-origin' });
        if (!response.ok) throw new Error('not read');
        const found = parseBookingList(await response.json());
        if (!stale) {
          setAlerts(found);
          setUnread(false);
        }
      } catch {
        if (!stale) setUnread(true);
      }
    }
    void read();
    const timer = setInterval(() => void read(), pollMs);
    return () => {
      stale = true;
      clearInterval(timer);
    };
  }, [pollMs]);

  if (alerts.length === 0 && !unread) return null;

  return (
    <section className={styles.strip} aria-label="Booking alerts" data-el="ADV-OPEN-ALERTS">
      {alerts.length > 0 ? (
        <>
          <h2 className={styles.heading}>
            {alerts.length === 1 ? '1 booking alert to answer' : `${alerts.length} booking alerts to answer`}
          </h2>
          <ul className={styles.list}>
            {alerts.map((alert) => (
              <li key={alert.id}>
                <Banner
                  tone="warning"
                  title={
                    alert.status === 'not-reached'
                      ? `A service could not reach the patient for booking ${alert.reference}.`
                      : `A service withdrew booking ${alert.reference}.`
                  }
                  dataEl="ADV-OPEN-ALERT"
                >
                  <p className={styles.text}>Phone the caller, then answer the alert.</p>
                  <a href={`/advisor/case/${encodeURIComponent(alert.caseRef)}/options`}>{`Open case ${alert.caseRef}`}</a>
                </Banner>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {unread ? <Banner tone="info" title="We could not check for booking alerts." dataEl="ADV-OPEN-ALERTS-UNREAD" /> : null}
    </section>
  );
}
