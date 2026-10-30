'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffPost } from '@/lib/bff/client';
import { canApprove, decisionNoteError, missingText, NOTE_MAX_LENGTH, parseDecision } from '@/lib/registration/model';
import type { DecisionAction } from '@/lib/registration/types';
import styles from '../lead.module.css';
import { useRead } from '@/lib/bff/useRead';

// Check 4 of 4: decide (W29, ui-screens ApprovalWeb2 screen 6). Approve is unavailable until the back
// end lists nothing missing. The missing list is read from the back end and never worked out here.

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

export function DecideStep({ id }: { id: string }) {
  const read = useRead(`/api/bff/registrations/${encodeURIComponent(id)}/decision`, parseDecision);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<DecisionAction | null>(null);
  const [done, setDone] = useState<DecisionAction | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="The decision could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;
  const { missing } = read.data;
  const allowed = canApprove(missing);

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

  return (
    <main className={styles.page}>
      <p className={styles.meta}>Check 4 of 4</p>
      <h1 className={styles.heading}>Decide</h1>

      <h2 className={styles.section}>Before you can approve</h2>
      <ul className={styles.list}>
        {CHECKS.map((check) => (
          <li key={check} className={styles.meta}>
            <span>{check}</span> <span className={styles.tag}>{missing.includes(check) ? 'Missing' : 'Done'}</span>
          </li>
        ))}
      </ul>
      <p role="status">{allowed ? '' : missingText(missing)}</p>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.approve}
          aria-disabled={!allowed}
          data-el="LEAD-REG-APPROVE-BTN"
          onClick={() => void decide('approve')}
        >
          {allowed ? 'Approve' : 'Approve (not yet available)'}
        </button>
      </div>

      <div className={styles.field}>
        <label htmlFor={`decide-note-${id}`}>Note to the applicant</label>
        <p id={`decide-note-hint-${id}`} className={styles.hint}>
          Optional. Needed to send back or not approve. No patient information. Up to {NOTE_MAX_LENGTH} characters.
        </p>
        <textarea
          id={`decide-note-${id}`}
          className={styles.textarea}
          value={note}
          maxLength={NOTE_MAX_LENGTH}
          onChange={(e) => setNote(e.target.value)}
          aria-describedby={`decide-note-hint-${id}`}
          aria-invalid={error !== null}
        />
        {error !== null ? <p role="alert" className={styles.error}>{error}</p> : null}
      </div>

      <div className={styles.actions}>
        <Button variant="secondary" busy={busy === 'send-back'} onClick={() => void decide('send-back')} dataEl="LEAD-REG-SENDBACK-BTN">
          Send back with a note
        </Button>
        <Button variant="secondary" busy={busy === 'not-approve'} onClick={() => void decide('not-approve')} dataEl="LEAD-REG-NOTAPPROVED-BTN">
          Not approved: out of scope
        </Button>
      </div>

      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
      {done !== null ? <p aria-live="polite">{DONE_TEXT[done]}</p> : null}
    </main>
  );
}
