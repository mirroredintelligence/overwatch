'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { bffPost } from '@/lib/bff/client';
import { canApprove, decisionNoteError, missingText, NOTE_MAX_LENGTH, parseDecision } from '@/lib/registration/model';
import type { DecisionAction } from '@/lib/registration/types';
import styles from './DecideGoLive.module.css';
import page from '../lead-forms.module.css';
import { useRead } from '@/lib/bff/useRead';

// Check 4 of 4: decide (W29, board Rev1 layer 4, phone RvP2). Approve is a real disabled button, and it says
// what it waits for, until the back end lists nothing missing. The missing list is read from the back end and
// never worked out here.

const CHECKS: ReadonlyArray<string> = [
  'Automatic checks passed or explained',
  'Call-back done',
  'Scope decided',
  'Criteria second approval (waiting for the clinical lead)',
];

const DONE_TEXT: Record<DecisionAction, string> = {
  approve: 'Approved.',
  'send-back': 'Sent back. The applicant sees your note.',
  'not-approve': 'Not approved. The applicant sees your note.',
};

/** The words in brackets after the one thing still missing ("waiting for the clinical lead"), else a plain fallback. */
function approveLabel(missing: readonly string[]): string {
  if (missing.length === 0) return 'Approve';
  const only = missing.length === 1 ? /\(([^()]+)\)\s*$/.exec(missing[0] ?? '') : null;
  return `Approve (${only?.[1] ?? 'not yet available'})`;
}

/** The label and, for an open check, the words after it ("Waiting for the clinical lead"). */
function splitCheck(check: string): { name: string; wait: string | null } {
  const found = /^(.*?)\s*\(([^()]+)\)\s*$/.exec(check);
  if (found === null) return { name: check, wait: null };
  const wait = found[2] ?? '';
  return { name: found[1] ?? check, wait: wait.charAt(0).toUpperCase() + wait.slice(1) };
}

export function DecideStep({ id }: { id: string }) {
  const read = useRead(`/api/bff/registrations/${encodeURIComponent(id)}/decision`, parseDecision);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<DecisionAction | null>(null);
  const [done, setDone] = useState<DecisionAction | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') {
    return (
      <main className={page.page}>
        <h1 className={page.heading}>Decide</h1>
        <Banner tone="warning" title="The decision could not be loaded. Try again shortly." />
      </main>
    );
  }
  if (read.status === 'loading') {
    return (
      <main className={page.page}>
        <Loading label="Loading the decision.">
          <Skeleton shape="title" width="40%" />
          <Skeleton shape="block" />
        </Loading>
      </main>
    );
  }
  const { missing } = read.data;
  const allowed = canApprove(missing);
  // The checks the page knows by name, then any other item the back end lists, so the list is always whole.
  const rows = [...CHECKS, ...missing.filter((item) => !CHECKS.includes(item))];

  const decide = async (action: DecisionAction) => {
    if (action === 'approve' && !allowed) return;
    const found = decisionNoteError(action, note);
    setError(found);
    if (found !== null) return;
    setBusy(action);
    setFailure(null);
    setDone(null);
    const trimmed = note.trim();
    const result = await bffPost(`/api/bff/registrations/${encodeURIComponent(id)}/decision`, {
      action,
      ...(action !== 'approve' && trimmed !== '' ? { note: trimmed } : {}),
    });
    setBusy(null);
    if (result.ok) setDone(action);
    else setFailure('That decision was not recorded. Check the checks above and try again.');
  };

  const hintId = `decide-note-hint-${id}`;
  const noteId = `decide-note-${id}`;
  const working = busy !== null;

  return (
    <main className={page.page}>
      <div className={styles.card}>
        <div>
          <p className={styles.eyebrow}>Check 4 of 4</p>
          <h1 className={styles.title}>Decide</h1>
        </div>

        <ul className={styles.checks} aria-label="Before you can approve">
          {rows.map((check) => {
            const open = missing.includes(check);
            const { name, wait } = splitCheck(check);
            return (
              <li key={check} className={styles.check}>
                <span className={`${styles.mark} ${open ? styles.markOpen : styles.markDone}`} aria-hidden="true">
                  {open ? '◔' : '✓'}
                </span>
                <span className={styles.checkBody}>
                  {open && wait !== null ? (
                    <>
                      {name}. <strong>{wait}.</strong>
                    </>
                  ) : (
                    name
                  )}{' '}
                  <span className={styles.word}>{open ? 'Missing' : 'Done'}</span>
                </span>
              </li>
            );
          })}
        </ul>
        <p role="status" className={styles.status}>
          {allowed ? '' : missingText(missing)}
        </p>

        <div className={styles.field}>
          <label htmlFor={noteId} className={styles.label}>
            Note to the applicant
          </label>
          <p id={hintId} className={styles.hint}>
            Optional. Needed to send back or not approve. No patient information. Up to {NOTE_MAX_LENGTH} characters.
          </p>
          <textarea
            id={noteId}
            className={styles.textarea}
            value={note}
            maxLength={NOTE_MAX_LENGTH}
            onChange={(e) => setNote(e.target.value)}
            aria-describedby={hintId}
            aria-invalid={error !== null}
          />
          {error !== null ? (
            <p role="alert" className={styles.error}>
              <span aria-hidden="true">▲ </span>
              <span>{error}</span>
            </p>
          ) : null}
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            disabled={!allowed || working}
            aria-busy={busy === 'approve' ? 'true' : undefined}
            data-el="LEAD-REG-APPROVE-BTN"
            onClick={() => void decide('approve')}
          >
            {approveLabel(missing)}
          </button>
          <button
            type="button"
            className={styles.outline}
            disabled={working}
            aria-busy={busy === 'send-back' ? 'true' : undefined}
            data-el="LEAD-REG-SENDBACK-BTN"
            onClick={() => void decide('send-back')}
          >
            Send back with a note
          </button>
          <button
            type="button"
            className={styles.quiet}
            disabled={working}
            aria-busy={busy === 'not-approve' ? 'true' : undefined}
            data-el="LEAD-REG-NOTAPPROVED-BTN"
            onClick={() => void decide('not-approve')}
          >
            Not approved: out of scope
          </button>
        </div>

        {failure !== null ? (
          <p role="alert" className={styles.error}>
            <span aria-hidden="true">▲ </span>
            <span>{failure}</span>
          </p>
        ) : null}
        {done !== null ? (
          <p aria-live="polite" className={styles.polite}>
            {DONE_TEXT[done]}
          </p>
        ) : null}
      </div>
    </main>
  );
}
