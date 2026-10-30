'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffPost } from '@/lib/bff/client';
import { useRead } from '@/lib/bff/useRead';
import { acceptsLine, doesNotAcceptLine, shortDate } from '@/lib/criteria/model';
import { parsePending } from '@/lib/criteria/pending';
import styles from '@/components/lead/lead.module.css';

// The clinical lead's second approval of a criteria change (W31, ui-screens CriteriaOwner screen 10).
// The approver sees what changed and why; the author sees that another clinical lead must approve.
// A refusal from the back end (403, or the non-revealing 404 for a role or the author) says so.

const NOT_ALLOWED = 'You cannot approve criteria for this service.';

export function CriteriaApproval({ serviceId }: { serviceId: string }) {
  const read = useRead(`/api/bff/criteria/${encodeURIComponent(serviceId)}/pending`, parsePending);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'approve' | 'send-back' | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="This change could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;
  const pending = read.data;

  const decide = async (decision: 'approve' | 'send-back') => {
    if (decision === 'send-back' && note.trim() === '') {
      setError('Enter a note for the criteria owner');
      return;
    }
    setError(null);
    setBusy(decision);
    setFailure(null);
    const trimmed = note.trim();
    const result = await bffPost(`/api/bff/criteria/${encodeURIComponent(serviceId)}/pending/decision`, {
      decision,
      ...(decision === 'send-back' ? { note: trimmed } : {}),
    });
    setBusy(null);
    if (result.ok) {
      const version = (result.data as { version?: unknown } | undefined)?.version;
      setDone(decision === 'approve' ? `Approved. Advisors now see version ${String(version)}.` : 'Sent back. The criteria owner sees your note.');
    } else if (result.status === 403 || result.status === 404) {
      setFailure(NOT_ALLOWED);
    } else {
      setFailure('That decision was not recorded. Try again.');
    }
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>{`Second approval · ${pending.serviceName}`}</h1>

      {pending.changes !== null ? (
        <>
          <h2 className={styles.section}>What changed</h2>
          <ul className={styles.steps}>
            {pending.changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>
        </>
      ) : pending.full !== undefined ? (
        <>
          <h2 className={styles.section}>Criteria</h2>
          <p>{acceptsLine(pending.full)}</p>
          <p>{doesNotAcceptLine(pending.full)}</p>
          <p className={styles.meta}>{`Owner: ${pending.full.ownerRole} · review by ${shortDate(pending.full.reviewBy)} · version ${pending.full.version}`}</p>
        </>
      ) : null}

      {pending.reason !== '' ? <p>{`Reason from ${pending.authorRole}: ${pending.reason}`}</p> : null}

      {pending.isAuthor ? (
        <p role="status" className={styles.hint}>You wrote this change. Another clinical lead must approve it.</p>
      ) : (
        <>
          <p className={styles.section}>Safe for advisors to rely on?</p>
          <div className={styles.field}>
            <label htmlFor={`approval-note-${serviceId}`}>Note (if sending back)</label>
            <p className={styles.hint}>Optional, unless you send it back.</p>
            <textarea id={`approval-note-${serviceId}`} className={styles.textarea} value={note} onChange={(e) => setNote(e.target.value)} aria-invalid={error !== null} />
            {error !== null ? <p role="alert" className={styles.error}>{error}</p> : null}
          </div>
          <div className={styles.actions}>
            <Button variant="primary" busy={busy === 'approve'} onClick={() => void decide('approve')} dataEl="OWN-APPROVE-YES-BTN">
              Yes, approve
            </Button>
            <Button variant="secondary" busy={busy === 'send-back'} onClick={() => void decide('send-back')} dataEl="OWN-APPROVE-SENDBACK-BTN">
              Send back
            </Button>
          </div>
        </>
      )}

      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
      {done !== null ? <p aria-live="polite">{done}</p> : null}
      <p className={styles.hint}>Advisors see the new version only after you publish. The old version stays in the audit record.</p>
    </main>
  );
}
