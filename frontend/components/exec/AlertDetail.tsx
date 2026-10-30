'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { alertTime, alertTitle, type AlertItem } from '@/lib/exec/alerts';
import { telHref } from '@/lib/exec/call';
import { bffRequest } from '@/lib/bff/browser';
import styles from './Exec.module.css';

// One alert (W40, ExecApp2 screen 5). Acknowledging tells others it is being handled and does not change
// the board. Snoozing moves the next escalation one hour on.

const STATE_WORD = { new: 'New', escalated: 'Escalated', acknowledged: 'Acknowledged', closed: 'Closed' } as const;
export const ACK_FAILED = 'Could not acknowledge. Try again.';
export const SNOOZE_FAILED = 'Could not snooze. Try again.';

export function AlertDetail({ alert, coordinationPhone = null }: { alert: AlertItem; coordinationPhone?: string | null }) {
  const [escalatesAt, setEscalatesAt] = useState(alert.escalatesAt);
  const [acknowledged, setAcknowledged] = useState(alert.state === 'acknowledged');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const acknowledge = async () => {
    setBusy(true);
    setError(null);
    const result = await bffRequest<{ status: string }>(`/api/bff/exec/alerts/${encodeURIComponent(alert.id)}/acknowledge`, { method: 'POST' });
    setBusy(false);
    if (!result.ok) return setError(ACK_FAILED);
    setAcknowledged(true);
  };

  const snooze = async () => {
    setBusy(true);
    setError(null);
    const result = await bffRequest<{ escalatesAt: string }>(`/api/bff/exec/alerts/${encodeURIComponent(alert.id)}/snooze`, { method: 'POST' });
    setBusy(false);
    if (!result.ok) return setError(SNOOZE_FAILED);
    setEscalatesAt(result.data.escalatesAt);
  };

  const open = alert.state === 'new' || alert.state === 'escalated';
  const escalation = escalatesAt === null
    ? 'If nobody acknowledges, your deputy is alerted.'
    : `If nobody acknowledges by ${alertTime(escalatesAt)}, your deputy is alerted.`;

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>{alertTitle(alert)}</h1>
      {alert.detail !== null ? <p>{alert.detail}</p> : null}
      <p>{STATE_WORD[alert.state]}{` · alerted ${alertTime(alert.raisedAt)}`}</p>
      {open && !acknowledged ? <p>{escalation}</p> : null}
      {alert.state === 'acknowledged' && alert.acknowledgedAt !== null ? <p>{`Acknowledged at ${alertTime(alert.acknowledgedAt)}`}</p> : null}
      {coordinationPhone !== null ? (
        <p>
          <a href={telHref(coordinationPhone)} className={styles.backLink} data-el="EXEC-ALERT-CALL-LINK">Call the duty coordinator</a>
          {' '}
          <span>{coordinationPhone}</span>
        </p>
      ) : null}
      {open && !acknowledged ? <p className={styles.footer}>Acknowledging tells others it is being handled.</p> : null}
      {acknowledged && alert.state !== 'acknowledged' ? <p role="status" className={styles.error}>Acknowledged.</p> : null}
      {open && !acknowledged ? (
        <div className={styles.actions}>
          <Button variant="primary" busy={busy} onClick={acknowledge} dataEl="EXEC-ALERT-ACK-BTN">Acknowledge</Button>
          <Button variant="secondary" busy={busy} onClick={snooze} dataEl="EXEC-ALERT-SNOOZE-BTN">Snooze for 1 hour</Button>
        </div>
      ) : null}
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      <div className={styles.actions}>
        <Link href="/planning/alerts" className={styles.backLink}>Back to alerts</Link>
      </div>
    </div>
  );
}
