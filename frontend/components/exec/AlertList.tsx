'use client';

import Link from 'next/link';
import { useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { alertTime, alertTitle, type AlertItem } from '@/lib/exec/alerts';
import styles from './Exec.module.css';

// The executive's alerts (W40, ExecApp1 screen 4). Tabs: Open, Acknowledged, Closed. The back end lists
// open alerts only, so the Acknowledged tab holds the alerts this person acknowledged in this visit, and
// the Closed tab says it is not available yet. An acknowledgement moves its card at once; a failure moves
// it back and says so.

type Tab = 'open' | 'acknowledged' | 'closed';
const TABS: readonly Tab[] = ['open', 'acknowledged', 'closed'];
export const ACK_FAILED = 'Could not acknowledge. Try again.';

export function AlertList({ open: initialOpen }: { open: AlertItem[] }) {
  const [open, setOpen] = useState(initialOpen);
  const [acknowledged, setAcknowledged] = useState<AlertItem[]>([]);
  const [tab, setTab] = useState<Tab>('open');
  const [error, setError] = useState<string | null>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ open: null, acknowledged: null, closed: null });
  const baseId = useId();
  const labelOf = (name: Tab) => (name === 'open' ? `Open (${open.length})` : name === 'acknowledged' ? 'Acknowledged' : 'Closed');

  const select = (next: Tab) => {
    setTab(next);
    tabRefs.current[next]?.focus();
  };

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = TABS.indexOf(tab);
    if (event.key === 'ArrowRight') select(TABS[(index + 1) % TABS.length] ?? 'open');
    else if (event.key === 'ArrowLeft') select(TABS[(index + TABS.length - 1) % TABS.length] ?? 'open');
    else if (event.key === 'Home') select('open');
    else if (event.key === 'End') select('closed');
    else return;
    event.preventDefault();
  };

  const acknowledge = async (item: AlertItem) => {
    setError(null);
    setOpen((current) => current.filter((a) => a.id !== item.id));
    setAcknowledged((current) => [item, ...current]);
    const result = await bffRequest(`/api/bff/exec/alerts/${encodeURIComponent(item.id)}/acknowledge`, { method: 'POST' });
    if (result.ok) return;
    setAcknowledged((current) => current.filter((a) => a.id !== item.id));
    setOpen((current) => [item, ...current]);
    setError(ACK_FAILED);
  };

  const card = (item: AlertItem, actions: boolean) => (
    <article key={item.id} className={styles.card} aria-label={alertTitle(item)}>
      <h2 className={styles.cardTitle}>{alertTitle(item)}</h2>
      {item.detail !== null ? <p>{item.detail}</p> : null}
      <p className={styles.footer}>
        {`${item.state === 'escalated' ? 'Escalated' : 'New'} · alerted ${alertTime(item.raisedAt)}`}
      </p>
      {actions ? (
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => acknowledge(item)} dataEl="EXEC-ALERT-ACK-BTN">Acknowledge</Button>
          <Link href={`/planning/alerts/${encodeURIComponent(item.id)}`} className={styles.backLink} data-el="EXEC-ALERT-OPEN-BTN">Open</Link>
        </div>
      ) : null}
    </article>
  );

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>Alerts</h1>
      <div role="tablist" aria-label="Alerts" className={styles.tabs}>
        {TABS.map((name) => (
          <button
            key={name}
            ref={(node) => { tabRefs.current[name] = node; }}
            id={`${baseId}-${name}-tab`}
            type="button"
            role="tab"
            aria-selected={tab === name}
            aria-controls={`${baseId}-${name}-panel`}
            tabIndex={tab === name ? 0 : -1}
            onClick={() => setTab(name)}
            onKeyDown={onTabKey}
            className={styles.tab}
            data-el={`EXEC-ALERTS-TAB-${name.toUpperCase()}`}
          >
            {labelOf(name)}
          </button>
        ))}
      </div>

      {error ? <p role="alert" className={styles.error}>{error}</p> : null}

      <div role="tabpanel" id={`${baseId}-open-panel`} aria-labelledby={`${baseId}-open-tab`} hidden={tab !== 'open'}>
        {open.length === 0 ? <p>No open alerts.</p> : open.map((item) => card(item, true))}
      </div>
      <div role="tabpanel" id={`${baseId}-acknowledged-panel`} aria-labelledby={`${baseId}-acknowledged-tab`} hidden={tab !== 'acknowledged'}>
        {acknowledged.length === 0 ? <p>Nothing acknowledged in this visit.</p> : acknowledged.map((item) => card(item, false))}
      </div>
      <div role="tabpanel" id={`${baseId}-closed-panel`} aria-labelledby={`${baseId}-closed-tab`} hidden={tab !== 'closed'}>
        <p>Closed alerts are not available yet.</p>
      </div>
    </div>
  );
}
