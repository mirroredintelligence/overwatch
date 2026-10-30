'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { sessionCsrf, statusAction } from '@/lib/register/browser';
import styles from '../register.module.css';

// Not approved (W27, ApprovalStates): the reason, and the applicant may ask for a review once.

const ASKED = 'We have asked the shift lead to look again.';
const FAILED = 'We could not send the request. Try again.';

export function NotApproved({ registrationId, reason }: { registrationId: string; reason?: string }) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    const csrf = await sessionCsrf();
    const ok = csrf !== null && (await statusAction(registrationId, 'review-request', csrf));
    setBusy(false);
    setNotice(ok ? ASKED : FAILED);
  }

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>We cannot add this service yet</h1>
      {reason !== undefined ? <p className={styles.text}>Reason: {reason}.</p> : null}
      <p className={styles.text}>You do not need to do anything. We will contact you if the scope changes.</p>
      <p className={styles.note}>You can ask for a review if you think this is wrong.</p>
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="REG-STATUS-APP-REVIEW-BTN" onClick={() => void ask()}>
          Ask for a review
        </Button>
        <Link className={styles.backLink} href="/register/services">
          Close
        </Link>
      </div>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
    </div>
  );
}
