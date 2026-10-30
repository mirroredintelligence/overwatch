'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { maskMobile } from '@/lib/register/phone';
import { sessionCsrf, statusAction, type StatusDetails } from '@/lib/register/browser';
import styles from '../register.module.css';

// Are these still right? (W27, ApprovalApplicant "reverify"): asked every 30 days, and when the
// reporting phone changes. The reporting phone is shown masked, as the code screen shows it.

const CONFIRMED = 'Your details are confirmed.';
const FAILED = 'We could not send that. Try again.';
/** [ASSUMED] The re-check period: the back end's text-code check is every 30 days (DEC-044). */
const PERIOD = '30 days';

export function Reverify({ registrationId, serviceName, details }: { registrationId: string; serviceName: string; details: StatusDetails }) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    const csrf = await sessionCsrf();
    const ok = csrf !== null && (await statusAction(registrationId, 'confirm-details', csrf));
    setBusy(false);
    setNotice(ok ? CONFIRMED : FAILED);
  }

  const rows: [string, string | undefined][] = [
    ['Service', serviceName],
    ['Phone for the coordination team', details.spoaPhone],
    ['Criteria owner', details.criteriaOwner],
    ['Reporting phone', details.reportingPhoneEnding === undefined ? undefined : maskMobile(`07xxxxxxxx${details.reportingPhoneEnding}`)],
  ];

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>Are these still right?</h1>
      <p className={styles.text}>We ask every {PERIOD}, and whenever your reporting phone changes.</p>
      <dl className={styles.locked}>
        {rows.map(([label, value]) =>
          value === undefined ? null : (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ),
        )}
      </dl>
      <p className={styles.note}>If the reporting phone changes, the shift lead phones your service before the new phone goes live.</p>
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="REG-STATUS-CONFIRM-BTN" onClick={() => void confirm()}>
          All correct
        </Button>
        <Link className={styles.backLink} href={`/register/${encodeURIComponent(registrationId)}/review`} data-el="REG-STATUS-REVIEW-BTN">
          Something changed
        </Link>
      </div>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
    </div>
  );
}
