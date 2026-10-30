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

  useEffect(() => {
    let live = true;
    bffFetch<SummaryView>(`/api/bff/cases/${encodeURIComponent(caseId)}/summary`).then((reply) => {
      if (!live) return;
      if (reply.ok) {
        setSummary(reply.body);
        setReference(reply.body.reference);
      }
      else if (reply.status === 409 && reply.code === 'closed') setClosed(true);
      else setFailed(true);
    });
    return () => {
      live = false;
    };
  }, [caseId]);

  if (closed) return <CallClosed reference={reference} />;

  return (
    <div className={styles.screen}>
      <h1 className={styles.heading}>Record outcome</h1>
      <p className={styles.text}>{reference === null ? 'Case number not read yet' : `Case ${reference}`}</p>
      <section id="outcome" aria-label="Outcome">
        <OutcomeForm
          caseId={caseId}
          preselect={preselect}
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
