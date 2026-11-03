'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import { sessionCsrf, statusAction } from '@/lib/register/browser';
import styles from '../status.module.css';

// Approved, the test to come (W27, ApprovalApplicant panel 4). The applicant is not on the board until
// the test is answered.

const SENT = 'Test sent. Answer it on your phone.';
const FAILED = 'We could not send the test. Try again.';

export function Approved({ registrationId }: { registrationId: string }) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function send() {
    setBusy(true);
    const csrf = await sessionCsrf();
    const ok = csrf !== null && (await statusAction(registrationId, 'test', csrf));
    setBusy(false);
    setNotice(ok ? SENT : FAILED);
  }

  return (
    <section className={styles.card} aria-label="Approved">
      <div className={styles.tagRow}>
        <StatusTag variant="confirmed">Approved</StatusTag>
      </div>
      <h1 className={styles.heading}>One last step: a test</h1>
      <p className={styles.text}>
        We send a test notification to your phone. Answer it as you normally would. This proves you receive and answer prompts.
      </p>
      <p className={styles.strong}>You are not on the board until the test is answered.</p>
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="REG-STATUS-TEST-BTN" onClick={() => void send()}>
          Send my test notification
        </Button>
      </div>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
    </section>
  );
}
