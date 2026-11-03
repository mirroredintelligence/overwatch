'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { londonTime } from '@/lib/board/format';
import { bffPost } from '@/lib/bff/client';
import { parseDecision, parseOverview, setLiveEnabled } from '@/lib/registration/model';
import type { Decision, Overview } from '@/lib/registration/types';
import styles from './DecideGoLive.module.css';
import page from '../lead-forms.module.css';
import { useRead } from '@/lib/bff/useRead';

// Go live (W29, board Rev1 layer 5, phone RvP2). Set live is offered only once the test notification
// has been answered from the registered phone. The board preview is a status, not a figure: a figure is
// not known until the service reports one, so no number is made up here. The approval time is shown only
// when the back end returns one, so the first step names who approved.

function Step({ done, children }: { done: boolean; children: string }) {
  return (
    <li className={styles.step}>
      <span className={`${styles.dot} ${done ? styles.dotDone : styles.dotOpen}`} aria-hidden="true">
        {done ? '✓' : ''}
      </span>
      <span className={styles.stepText}>
        <span>{children}</span> <span className={styles.word}>{done ? 'Done' : 'Not yet'}</span>
      </span>
    </li>
  );
}

function Record({ decision }: { decision: Decision }) {
  return (
    <section aria-labelledby="registration-record">
      <h2 id="registration-record" className={styles.recordHeading}>
        Registration record
      </h2>
      <ol className={styles.record}>
        {decision.timeline.map((item) => (
          <li key={`${item.at}-${item.label}`}>
            <span className={styles.recordTime}>{londonTime(item.at)}</span> <span>{item.label}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function GoLive({ id }: { id: string }) {
  const path = encodeURIComponent(id);
  const overview = useRead<Overview>(`/api/bff/registrations/${path}`, parseOverview);
  const decision = useRead<Decision>(`/api/bff/registrations/${path}/decision`, parseDecision);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (overview.status === 'failed' || decision.status === 'failed') {
    return (
      <main className={page.page}>
        <Banner tone="warning" title="Go live could not be loaded. Try again shortly." />
      </main>
    );
  }
  if (overview.status === 'loading' || decision.status === 'loading') {
    return (
      <main className={page.page}>
        <Loading label="Loading go live.">
          <Skeleton shape="title" width="40%" />
          <Skeleton shape="block" />
        </Loading>
      </main>
    );
  }

  const name = overview.data.serviceName;
  const today = decision.data;
  const approvers = today.approvedBy.length > 0 ? today.approvedBy.join(' and ') : null;
  const ready = setLiveEnabled(today);
  const canSetLive = ready && !live;

  const setServiceLive = async () => {
    setBusy(true);
    setFailure(null);
    const result = await bffPost(`/api/bff/registrations/${path}/go-live`);
    setBusy(false);
    if (result.ok) setLive(true);
    else setFailure('The service could not be set live. Check the test and try again.');
  };

  return (
    <main className={page.page}>
      <div className={`${styles.card} ${styles.narrow}`}>
        <div>
          <p className={styles.eyebrow}>After approval</p>
          <h1 className={styles.title}>Go live: {name}</h1>
        </div>

        <ol className={styles.steps} aria-label="Before it goes live">
          <Step done={approvers !== null}>{approvers !== null ? `Approved by ${approvers}` : 'Approval not recorded yet.'}</Step>
          <Step done={today.test.sentAt !== undefined}>
            {today.test.sentAt !== undefined ? `Test notification sent ${londonTime(today.test.sentAt)}` : 'Test notification not sent yet.'}
          </Step>
          <Step done={today.test.answeredAt !== undefined}>
            {today.test.answeredAt !== undefined
              ? `Test answered ${londonTime(today.test.answeredAt)} from the registered phone`
              : 'Test not answered yet.'}
          </Step>
        </ol>

        <section className={styles.preview} aria-labelledby="board-preview">
          <h2 id="board-preview" className={styles.previewHeading}>
            How it will look on the board
          </h2>
          <div className={styles.previewRow}>
            <strong className={styles.previewName}>{name}</strong>
            <StatusBadge status="accepting" />
            <span className={styles.previewNote}>A status, until they report a number.</span>
          </div>
        </section>

        {!ready ? <p className={styles.status}>Set live opens when the test is answered from the registered phone.</p> : null}

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            disabled={!canSetLive || busy}
            aria-busy={busy ? 'true' : undefined}
            data-el="LEAD-REG-SETLIVE-BTN"
            onClick={() => void setServiceLive()}
          >
            Set live
          </button>
          <a className={styles.quiet} href={`/lead/registrations/${path}`}>
            Back
          </a>
        </div>
        {failure !== null ? (
          <p role="alert" className={styles.error}>
            <span aria-hidden="true">▲ </span>
            <span>{failure}</span>
          </p>
        ) : null}
        {live ? (
          <p aria-live="polite" className={styles.polite}>
            The service is live.
          </p>
        ) : null}

        <Record decision={today} />
      </div>
    </main>
  );
}
