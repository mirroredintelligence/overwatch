'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { ErrorSummary } from '@/components/forms/ErrorSummary';
import { loadReview, submitRegistration, sessionCsrf, type ReviewRow } from '@/lib/register/browser';
import type { FieldIssue } from '@/lib/register/types';
import styles from './register.module.css';

// Registration step 5, the review (W26, artboard RegisterFlow3 panel 9). Each section says whether it
// is complete; Submit goes only when all five are. A section that needs attention is listed in the
// summary, and nothing is sent.

export type ReviewListProps = { registrationId: string };

type Load = { kind: 'loading' } | { kind: 'open'; rows: ReviewRow[] } | { kind: 'unavailable' } | { kind: 'signed-out' };

const SECTIONS: Record<string, { title: string; step: string }> = {
  organisation: { title: 'Organisation', step: 'organisation' },
  location: { title: 'Location', step: 'location' },
  service: { title: 'Service', step: 'service' },
  reporting: { title: 'Capacity reporting', step: 'reporting' },
  api: { title: 'API', step: 'reporting' },
};
const WORDS: Record<ReviewRow['status'], string> = { complete: 'Complete', 'needs-attention': 'Needs attention' };
const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';
const SUBMIT_FAILED = 'We could not submit your registration. Try again.';
const SAVED = 'Draft saved.';

export function ReviewList({ registrationId }: ReviewListProps) {
  const router = useRouter();
  const base = `/register/${encodeURIComponent(registrationId)}`;
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [errors, setErrors] = useState<FieldIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    void loadReview(registrationId).then((outcome) => {
      if (!alive) return;
      setLoad(outcome.kind === 'open' ? { kind: 'open', rows: outcome.sections } : { kind: outcome.kind });
    });
    return () => {
      alive = false;
    };
  }, [registrationId]);

  async function submit() {
    if (load.kind !== 'open') return;
    const attention = load.rows.filter((row) => row.status === 'needs-attention');
    if (attention.length > 0) {
      setErrors(
        attention.map((row) => ({ field: `section-${row.key}`, message: `${SECTIONS[row.key]?.title ?? row.key} needs attention` })),
      );
      setNotice(null);
      return;
    }
    const csrf = await sessionCsrf();
    if (csrf === null) {
      setNotice(SIGNED_OUT);
      return;
    }
    setBusy(true);
    const outcome = await submitRegistration(registrationId, csrf);
    setBusy(false);
    if (outcome.kind === 'saved') {
      router.push(`${base}/submitted`);
      return;
    }
    if (outcome.kind === 'errors') {
      setErrors(outcome.errors);
      return;
    }
    setNotice(SUBMIT_FAILED);
  }

  const header = (
    <>
      <p className={styles.product}>DIUCS capacity</p>
      <p className={styles.note}>Step 5 of 5 · Review</p>
      <h1 className={styles.heading}>Check your details</h1>
    </>
  );

  if (load.kind === 'loading') return <div className={styles.stack}>{header}<p className={styles.text}>Loading your registration.</p></div>;
  if (load.kind !== 'open') {
    return (
      <div className={styles.stack}>
        {header}
        <p className={styles.notice} role="status">{load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}</p>
      </div>
    );
  }

  return (
    <div className={styles.stack}>
      {header}
      <ErrorSummary errors={errors} />
      <ul className={styles.rows}>
        {load.rows.map((row) => {
          const section = SECTIONS[row.key] ?? { title: row.key, step: row.key };
          return (
            <li key={row.key} id={`section-${row.key}`} className={styles.row} aria-labelledby={`section-${row.key}-title`}>
              <div className={styles.rowHead}>
                <span id={`section-${row.key}-title`} className={styles.rowTitle}>
                  {section.title}
                </span>
                <span className={row.status === 'complete' ? styles.complete : styles.attention}>{WORDS[row.status]}</span>
              </div>
              <p className={styles.note}>{row.summary}</p>
              <Link className={styles.changeLink} href={`${base}/${section.step}`} aria-label={`Change ${section.title}`}>
                Change
              </Link>
            </li>
          );
        })}
      </ul>
      <p className={styles.note}>The shift lead checks your details and sends a test text. You will not appear on the board until approved.</p>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="REG-REVIEW-SUBMIT-BTN" onClick={() => void submit()}>
          Submit for approval
        </Button>
        <Link className={styles.backLink} href={`${base}/reporting`}>
          Back
        </Link>
        <Button variant="neutral" dataEl="REG-REVIEW-SAVE-BTN" onClick={() => setNotice(SAVED)}>
          Save draft
        </Button>
      </div>
    </div>
  );
}
