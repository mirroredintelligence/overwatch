'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag } from '@/components/ui/StatusTag';
import { ErrorSummary } from '@/components/forms/ErrorSummary';
import { loadReview, submitRegistration, sessionCsrf, type ReviewRow } from '@/lib/register/browser';
import type { FieldIssue } from '@/lib/register/types';
import type { ChecklistState } from './RegistrationChecklist';
import { RegisterStage } from './RegisterStage';
import styles from './ReviewList.module.css';

// Registration step 5, the review (Reg board stage 5, RP3 board on a phone). Each section says whether it is
// complete, with Change; a section that needs attention has Fix this to its step instead. Submit is a real
// button, disabled until all five sections are complete, and says how many need attention. Nothing is sent
// from a disabled button.

export type ReviewListProps = { registrationId: string };

type Load = { kind: 'loading' } | { kind: 'open'; rows: ReviewRow[] } | { kind: 'unavailable' } | { kind: 'signed-out' };

// step: the route of the section; checklist: its number in the checklist (the API question sits in step 4).
const SECTIONS: Record<string, { title: string; step: string; checklist: number }> = {
  organisation: { title: 'Organisation', step: 'organisation', checklist: 1 },
  location: { title: 'Location', step: 'location', checklist: 2 },
  service: { title: 'Service', step: 'service', checklist: 3 },
  reporting: { title: 'Capacity reporting', step: 'reporting', checklist: 4 },
  api: { title: 'API', step: 'reporting', checklist: 4 },
};
const WORDS: Record<ReviewRow['status'], { word: string; variant: 'done' | 'problem' }> = {
  complete: { word: 'Complete', variant: 'done' },
  'needs-attention': { word: 'Needs attention', variant: 'problem' },
};
const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';
const SUBMIT_FAILED = 'We could not submit your registration. Try again.';
const SAVED_NOTE = 'Saved a moment ago';

function attentionWords(count: number): string {
  return count === 1 ? '1 section needs attention first' : `${count} sections need attention first`;
}

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

  const rows = load.kind === 'open' ? load.rows : [];
  const attention = rows.filter((row) => row.status === 'needs-attention');
  const blocked = attention.length > 0;

  // The checklist beside the review shows the same words: a step is complete unless one of its rows needs attention.
  const states: Partial<Record<number, ChecklistState>> = {};
  if (load.kind === 'open') {
    for (const step of [1, 2, 3, 4]) {
      const mine = rows.filter((row) => (SECTIONS[row.key]?.checklist ?? 0) === step);
      states[step] = mine.some((row) => row.status === 'needs-attention') ? 'needs-attention' : 'complete';
    }
  }

  async function submit() {
    // A disabled button cannot reach here; the guard keeps a section that needs attention from ever being sent.
    if (load.kind !== 'open' || blocked) return;
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
    <div>
      <p className={styles.step}>Step 5 of 5</p>
      <h1 className={styles.heading}>Check your details</h1>
    </div>
  );

  function frame(children: ReactNode) {
    return (
      <RegisterStage
        registrationId={registrationId}
        stage={5}
        states={states}
        savedNote={load.kind === 'open' ? SAVED_NOTE : undefined}
        phoneAction={
          load.kind === 'open'
            ? { primary: { label: 'Submit for approval', disabled: blocked, busy, onClick: () => void submit() } }
            : undefined
        }
      >
        <div className={styles.card}>
          {header}
          {children}
        </div>
      </RegisterStage>
    );
  }

  if (load.kind === 'loading') {
    return frame(
      <Loading label="Loading your registration.">
        <SkeletonRows count={4} />
      </Loading>,
    );
  }
  if (load.kind !== 'open') {
    return frame(<p className={styles.notice} role="status">{load.kind === 'signed-out' ? SIGNED_OUT : LOAD_FAILED}</p>);
  }

  return frame(
    <>
      <ErrorSummary errors={errors} />
      <ul className={styles.rows}>
        {rows.map((row) => {
          const section = SECTIONS[row.key] ?? { title: row.key, step: row.key, checklist: 0 };
          const { word, variant } = WORDS[row.status];
          const needs = row.status === 'needs-attention';
          return (
            <li key={row.key} id={`section-${row.key}`} className={styles.row} data-state={row.status} aria-labelledby={`section-${row.key}-title`}>
              <div className={styles.text}>
                <span className={styles.status}>
                  <StatusTag variant={variant}>{word}</StatusTag>
                </span>
                <div className={styles.body}>
                  <div id={`section-${row.key}-title`} className={styles.title}>
                    {section.title}
                  </div>
                  <div className={styles.summary}>{row.summary}</div>
                </div>
              </div>
              {needs ? (
                <Link className={styles.fix} href={`${base}/${section.step}`} aria-label={`Fix this: ${section.title}`}>
                  Fix this
                </Link>
              ) : (
                <Link className={styles.change} href={`${base}/${section.step}`} aria-label={`Change ${section.title}`}>
                  Change
                </Link>
              )}
            </li>
          );
        })}
      </ul>
      <p className={styles.after}>Your shift lead checks your details and sends a test text. You will not appear on the board until approved.</p>
      {notice !== null ? <p className={styles.notice} role="status">{notice}</p> : null}
      <div className={styles.actions}>
        <span className={styles.submit}>
          <Button variant="primary" busy={busy} disabled={blocked} dataEl="REG-REVIEW-SUBMIT-BTN" onClick={() => void submit()}>
            Submit for approval
          </Button>
        </span>
        {blocked ? <p className={styles.count}>{attentionWords(attention.length)}</p> : null}
        <Link className={styles.back} href={`${base}/reporting`}>
          Back
        </Link>
      </div>
    </>,
  );
}
