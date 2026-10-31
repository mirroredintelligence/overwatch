'use client';

import { useEffect, useState } from 'react';
import { bffFetch } from '@/lib/advisor/browser';
import type { TextOutcome } from '@/lib/advisor/outcome';
import type { SummaryView } from '@/lib/advisor/summary';
import { CallClosed } from './CallClosed';
import { OutcomeForm } from './OutcomeForm';
import { SummaryCopy } from './SummaryCopy';
import styles from './finish.module.css';

// The finish screen (W15): the outcome, then the summary to copy. When the outcome is saved the case
// is closed and this screen forgets the summary (the postcode and needs), so they are gone from the
// page as well as from the state.

type Props = { caseId: string; preselect: TextOutcome | null };

export function FinishScreen({ caseId, preselect }: Props) {
  const [summary, setSummary] = useState<SummaryView | null>(null);
  const [failed, setFailed] = useState(false);
  const [closed, setClosed] = useState(false);
  // The case number is kept when the summary is forgotten: it is the one thing the closed screen names.
  const [reference, setReference] = useState<string | null>(null);
  // The service the call went to, once the advisor chooses it: the summary is read again naming it, so the
  // referral that is copied says where the patient went, how it was booked and how old the figure was.
  const [destination, setDestination] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const query = destination === null ? '' : `?destination=${encodeURIComponent(destination)}`;
    bffFetch<SummaryView>(`/api/bff/cases/${encodeURIComponent(caseId)}/summary${query}`).then((reply) => {
      if (!live) return;
      if (reply.ok) {
        setFailed(false);
        setSummary(reply.body);
        setReference(reply.body.reference);
      }
      else if (reply.status === 409 && reply.code === 'closed') setClosed(true);
      else {
        // A summary that could not be read again is not left on screen: it would lack the destination.
        setSummary(null);
        setFailed(true);
      }
    });
    return () => {
      live = false;
    };
  }, [caseId, destination]);

  if (closed) return <CallClosed reference={reference} />;

  return (
    <div className={styles.screen}>
      <h1 className={styles.heading}>Record outcome</h1>
      <p className={styles.text}>{reference === null ? 'Case number not read yet' : `Case ${reference}`}</p>
      <section id="outcome" aria-label="Outcome">
        <OutcomeForm
          caseId={caseId}
          preselect={preselect}
          onDestinationChange={setDestination}
          onClosed={() => {
            setSummary(null);
            setClosed(true);
          }}
        />
      </section>
      {summary !== null ? <SummaryCopy summary={summary} /> : null}
      {summary === null && failed ? <p role="alert" className={styles.error}>The summary could not be read.</p> : null}
      {summary === null && !failed ? <p className={styles.text}>Loading the summary.</p> : null}
    </div>
  );
}
