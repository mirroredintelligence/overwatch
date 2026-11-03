'use client';

import { useEffect, useRef, useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { bffPost } from '@/lib/bff/client';
import { useRead } from '@/lib/bff/useRead';
import { acceptsLine, doesNotAcceptLine, shortDate } from '@/lib/criteria/model';
import { parsePending } from '@/lib/criteria/pending';
import styles from './CriteriaApproval.module.css';

// The clinical lead's second approval of a criteria change (W31, ui-screens CriteriaOwner screen 10).
// The diff is the screen: what changed, what it was, what it is now, the reason and who sent it. Approve is never
// the first thing focused; the diff is. The author sees that another clinical lead must approve.
// A refusal from the back end (403, or the non-revealing 404 for a role or the author) says so.

const NOT_ALLOWED = 'You cannot approve criteria for this service.';

// The back end sends each change as one sentence, "Youngest age 18 to 16". The was and now are cut from the end so
// they can sit in their own cells; a sentence without " X to Y" at its end stays whole, in the first cell.
function splitChange(change: string): { what: string; was: string; now: string } | null {
  const match = /^(.+) (\S+) to (\S+)$/.exec(change);
  return match === null ? null : { what: match[1] ?? change, was: match[2] ?? '', now: match[3] ?? '' };
}

export function CriteriaApproval({ serviceId }: { serviceId: string }) {
  const read = useRead(`/api/bff/criteria/${encodeURIComponent(serviceId)}/pending`, parsePending);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'approve' | 'send-back' | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [fullOpen, setFullOpen] = useState<boolean | null>(null);
  const diff = useRef<HTMLElement>(null);

  // The diff takes the focus once it is read, so the approve button is never the first thing a person reaches.
  useEffect(() => {
    if (read.status === 'ok') diff.current?.focus();
  }, [read.status]);

  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="This change could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') {
    return (
      <main className={styles.page}>
        <Loading label="Loading the change.">
          <div className={styles.skeleton}>
            <Skeleton shape="title" width="70%" />
            <Skeleton shape="block" />
            <Skeleton shape="block" width="60%" />
          </div>
        </Loading>
      </main>
    );
  }
  const pending = read.data;
  const registration = pending.changes === null;
  // A first registration has no diff, so its full criteria are the thing to judge and open by default.
  const showFull = fullOpen ?? registration;

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

  const approveLabel = pending.full !== undefined ? `Approve version ${pending.full.version}` : 'Approve this change';

  return (
    <main className={styles.page}>
      <div className={styles.layout}>
        <section ref={diff} tabIndex={-1} aria-label="What changed" className={styles.diffCard}>
          <p className={styles.kicker}>Waiting for you</p>
          <h1 className={styles.heading}>{registration ? `Criteria for ${pending.serviceName}` : `What changed in ${pending.serviceName}'s criteria`}</h1>

          {pending.changes !== null ? (
            <table className={styles.diffTable} aria-label="What changed">
              <thead>
                <tr>
                  <th scope="col">What</th>
                  <th scope="col">Was</th>
                  <th scope="col" aria-hidden="true" />
                  <th scope="col">Now</th>
                </tr>
              </thead>
              <tbody>
                {pending.changes.map((change) => {
                  const parts = splitChange(change);
                  return parts === null ? (
                    <tr key={change}>
                      <th scope="row" colSpan={4}>{change}</th>
                    </tr>
                  ) : (
                    <tr key={change}>
                      <th scope="row">{parts.what}</th>
                      <td><span className={styles.was}>{parts.was}</span></td>
                      <td aria-hidden="true" className={styles.arrow}>→</td>
                      <td><span className={styles.now}>{parts.now}</span></td>
                    </tr>
                  );
                })}
                <tr className={styles.same}>
                  <th scope="row">Everything else</th>
                  <td colSpan={3}>The same as the live version.</td>
                </tr>
              </tbody>
            </table>
          ) : null}

          {pending.reason !== '' ? (
            <div className={styles.reason}>
              <p className={styles.kicker}>The reason given</p>
              <p className={styles.reasonText}>{pending.reason}</p>
              <p className={styles.meta}>{`Sent by ${pending.authorRole}`}</p>
            </div>
          ) : null}

          {pending.full !== undefined ? (
            <Disclose
              open={showFull}
              onToggle={() => setFullOpen(!showFull)}
              title="See the full criteria as advisors will see them"
            >
              <div className={styles.full}>
                <p>{acceptsLine(pending.full)}</p>
                <p>{doesNotAcceptLine(pending.full)}</p>
                <p className={styles.meta}>{`Owner: ${pending.full.ownerRole} · review by ${shortDate(pending.full.reviewBy)} · version ${pending.full.version}`}</p>
              </div>
            </Disclose>
          ) : null}
        </section>

        <aside className={styles.side} aria-label="Your decision">
          {pending.isAuthor ? (
            <p role="status" className={styles.authorNote}>You wrote this change. Another clinical lead must approve it.</p>
          ) : (
            <>
              <section className={styles.rule}>
                <p className={styles.ruleKicker}>Two people, always</p>
                <p className={styles.ruleTitle}>You are the second approver.</p>
                <p className={styles.ruleBody}>
                  The person who wrote the change cannot approve it. Once you approve, the change goes live for advisors straight away. Your name and the time are logged.
                </p>
              </section>

              <section className={styles.decide}>
                <div className={styles.actions}>
                  <Button variant="primary" busy={busy === 'approve'} onClick={() => void decide('approve')} dataEl="OWN-APPROVE-YES-BTN">
                    {approveLabel}
                  </Button>
                  <Button variant="secondary" busy={busy === 'send-back'} onClick={() => void decide('send-back')} dataEl="OWN-APPROVE-SENDBACK-BTN">
                    Send it back with a note
                  </Button>
                </div>
                <div className={styles.field}>
                  <label htmlFor={`approval-note-${serviceId}`}>Note, if sending back</label>
                  <textarea
                    id={`approval-note-${serviceId}`}
                    className={styles.textarea}
                    placeholder="Say what to fix. They will see this."
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    aria-invalid={error !== null}
                  />
                  {error !== null ? <p role="alert" className={styles.error}>{error}</p> : null}
                </div>
              </section>
            </>
          )}

          {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
          {done !== null ? <p aria-live="polite" className={styles.done}>{done}</p> : null}
        </aside>
      </div>
    </main>
  );
}
