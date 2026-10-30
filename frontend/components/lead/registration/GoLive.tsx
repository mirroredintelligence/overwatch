'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { londonTime } from '@/lib/board/format';
import { bffPost } from '@/lib/bff/client';
import { parseDecision, parseOverview, setLiveEnabled } from '@/lib/registration/model';
import type { Decision, Overview } from '@/lib/registration/types';
import styles from '../lead.module.css';
import { useRead } from './useRead';

// Go live (W29, ui-screens ApprovalWeb2 screen 8). Set live is offered only once the test notification
// has been answered from the registered phone. The board preview is a status, not a figure: a figure is
// not known until the service reports one, so no number is made up here.

function Record({ decision }: { decision: Decision }) {
  return (
    <section aria-labelledby="registration-record">
      <h2 id="registration-record" className={styles.section}>Registration record</h2>
      <ol className={styles.steps}>
        {decision.timeline.map((item) => (
          <li key={`${item.at}-${item.label}`}>
            <span>{londonTime(item.at)}</span> <span>{item.label}</span>
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
    return <main className={styles.page}><Banner tone="warning" title="Go live could not be loaded. Try again shortly." /></main>;
  }
  if (overview.status === 'loading' || decision.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;

  const name = overview.data.serviceName;
  const today = decision.data;
  const approvers = today.approvedBy.length > 0 ? today.approvedBy.join(' and ') : null;
  const canSetLive = setLiveEnabled(today) && !live;

  const setServiceLive = async () => {
    setBusy(true);
    setFailure(null);
    const result = await bffPost(`/api/bff/registrations/${path}/go-live`);
    setBusy(false);
    if (result.ok) setLive(true);
    else setFailure('The service could not be set live. Check the test and try again.');
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Go live: {name}</h1>
      <p className={styles.meta}>{approvers !== null ? `Approved by ${approvers}` : 'Approval not recorded yet.'}</p>
      <p className={styles.meta}>
        {today.test.sentAt !== undefined ? `Test notification sent ${londonTime(today.test.sentAt)}` : 'Test notification not sent yet.'}
      </p>
      <p className={styles.meta}>
        {today.test.answeredAt !== undefined
          ? `Test answered ${londonTime(today.test.answeredAt)} from the registered phone`
          : 'Test not answered yet.'}
      </p>

      <section aria-labelledby="board-preview">
        <h2 id="board-preview" className={styles.section}>Board preview</h2>
        <p className={styles.meta}>
          {name} <StatusBadge status="accepting" />
        </p>
      </section>

      <div className={styles.actions}>
        <Button variant="primary" disabled={!canSetLive} busy={busy} onClick={setServiceLive} dataEl="LEAD-REG-SETLIVE-BTN">
          Set live
        </Button>
        <Button variant="neutral" href={`/lead/registrations/${path}`}>
          Back
        </Button>
      </div>
      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
      {live ? <p aria-live="polite">The service is live.</p> : null}

      <Record decision={today} />
    </main>
  );
}
