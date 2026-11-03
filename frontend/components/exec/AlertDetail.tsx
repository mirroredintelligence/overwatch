'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { alertTime, alertTitle, type AlertItem } from '@/lib/exec/alerts';
import { telHref } from '@/lib/exec/call';
import { bffRequest } from '@/lib/bff/browser';
import styles from './AlertDetail.module.css';

// One alert (W40, ExecApp2 screen 5; boards/planning/PAlert, PAlerts, PH3). Acknowledging tells others it is being
// handled and does not change the board. Snoozing moves the next escalation one hour on. The card is the same in
// every place it appears, Acknowledge then Call then Snooze (brief 6.2): `side` is beside the service at the
// alert state of the planning stage and, alone, on the standalone page; `pane` is the selected alert beside the
// list, which adds what happens if nobody acts and a way into the service.

export const STATE_WORD = { new: 'New', escalated: 'Escalated', acknowledged: 'Acknowledged', closed: 'Closed' } as const;
export const ACK_FAILED = 'Could not acknowledge. Try again.';
export const SNOOZE_FAILED = 'Could not snooze. Try again.';

const KIND_WORD = {
  'service-closed': 'closed unexpectedly',
  'over-capacity': 'over capacity',
  'not-updated': 'not updated',
  'system-pressure': 'system pressure rising',
} as const;

/** The shape and the word of an alert's tag: the kind while it is open, the outcome after. */
export function alertTag(alert: AlertItem): { variant: StatusTagVariant; word: string } {
  const word = STATE_WORD[alert.state];
  if (alert.state === 'acknowledged') return { variant: 'done', word };
  if (alert.state === 'closed') return { variant: 'closed', word };
  const variant: StatusTagVariant = alert.kind === 'over-capacity' ? 'over' : alert.kind === 'not-updated' ? 'paused' : alert.kind === 'service-closed' ? 'closed' : 'waiting';
  return { variant, word };
}

type Props = {
  alert: AlertItem;
  coordinationPhone?: string | null;
  layout?: 'side' | 'pane';
  /** Told once the back end has taken the acknowledgement. */
  onAcknowledged?: (id: string) => void;
};

export function AlertDetail({ alert, coordinationPhone = null, layout = 'side', onAcknowledged }: Props) {
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
    onAcknowledged?.(alert.id);
  };

  const snooze = async () => {
    setBusy(true);
    setError(null);
    const result = await bffRequest<{ escalatesAt: string }>(`/api/bff/exec/alerts/${encodeURIComponent(alert.id)}/snooze`, { method: 'POST' });
    setBusy(false);
    if (!result.ok) return setError(SNOOZE_FAILED);
    setEscalatesAt(result.data.escalatesAt);
  };

  const pane = layout === 'pane';
  const waiting = (alert.state === 'new' || alert.state === 'escalated') && !acknowledged;
  const tag = alertTag(alert);
  const summary = alert.kind === 'over-capacity' && alert.detail !== null
    ? `${alert.detail} over established capacity. Alerted ${alertTime(alert.raisedAt)}.`
    : `${alertTitle(alert)}. Alerted ${alertTime(alert.raisedAt)}.`;
  const escalation = escalatesAt === null
    ? 'If nobody acknowledges, your deputy is alerted.'
    : `If nobody acknowledges by ${alertTime(escalatesAt)}, your deputy is alerted.`;

  return (
    <section className={styles.card} aria-label={alertTitle(alert)} data-kind={alert.kind} data-layout={layout}>
      <div className={styles.head}>
        <div>
          <div className={styles.eyebrow}>{`Alert · ${KIND_WORD[alert.kind]}`}</div>
          <h2 className={styles.title}>{alert.serviceName ?? 'A service'}</h2>
        </div>
        <StatusTag variant={tag.variant}>{tag.word}</StatusTag>
      </div>
      <p className={styles.summary}>{summary}</p>
      {alert.state === 'acknowledged' && alert.acknowledgedAt !== null ? <p className={styles.summary}>{`Acknowledged at ${alertTime(alert.acknowledgedAt)}`}</p> : null}
      {waiting && !pane ? <p className={styles.note}>{escalation}</p> : null}
      {waiting && pane ? (
        <div className={styles.ladder}>
          <div className={styles.eyebrow}>What happens if nobody acts</div>
          <ol className={styles.steps}>
            <li className={styles.step}>
              <span className={styles.num} aria-hidden="true">1</span>
              <span>{`You are alerted now (${alertTime(alert.raisedAt)})`}</span>
            </li>
            {escalatesAt !== null ? (
              <li className={styles.step}>
                <span className={styles.num} data-later="" aria-hidden="true">2</span>
                <span>{`Your deputy is alerted at ${alertTime(escalatesAt)} if you have not acknowledged`}</span>
              </li>
            ) : null}
          </ol>
        </div>
      ) : null}
      {acknowledged && alert.state !== 'acknowledged' ? <p role="status" className={styles.done}>Acknowledged.</p> : null}
      <div className={styles.actions}>
        {waiting ? <Button variant="primary" busy={busy} onClick={acknowledge} dataEl="EXEC-ALERT-ACK-BTN">Acknowledge</Button> : null}
        {coordinationPhone !== null ? (
          <Button variant="secondary" href={telHref(coordinationPhone)} dataEl="EXEC-ALERT-CALL-LINK">Call the duty coordinator</Button>
        ) : null}
        {waiting ? <Button variant="neutral" busy={busy} onClick={snooze} dataEl="EXEC-ALERT-SNOOZE-BTN">Snooze for 1 hour</Button> : null}
        {pane && alert.serviceId !== null ? (
          <Button variant="neutral" href={`/planning/services/${encodeURIComponent(alert.serviceId)}`}>Open the service</Button>
        ) : null}
        {pane ? null : <Button variant="neutral" href="/planning/alerts">Back to alerts</Button>}
      </div>
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      {coordinationPhone !== null ? <p className={styles.small}>{coordinationPhone}</p> : null}
      {waiting ? <p className={styles.small}>Acknowledging tells others it is being handled. It does not change the board.</p> : null}
    </section>
  );
}
