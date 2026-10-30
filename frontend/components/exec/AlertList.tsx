'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { alertTime, alertTitle, type AlertItem } from '@/lib/exec/alerts';
import styles from './Exec.module.css';

// The executive's alerts (W40, ExecApp1 screen 4). Tabs: Open, Acknowledged, Closed. Open comes with the
// page; Acknowledged and Closed are read from the back end's own lists when their tab is opened (W7A,
// DEC-775), so they hold every alert, not only this visit's. An acknowledgement moves its card out of Open
// at once; a failure moves it back and says so. A list that could not be read is said, never shown as empty.

type Tab = 'open' | 'acknowledged' | 'closed';
const TABS: readonly Tab[] = ['open', 'acknowledged', 'closed'];
const STATE_WORD = { new: 'New', escalated: 'Escalated', acknowledged: 'Acknowledged', closed: 'Closed' } as const;
export const ACK_FAILED = 'Could not acknowledge. Try again.';

export function AlertList({ open: initialOpen }: { open: AlertItem[] }) {
  const [open, setOpen] = useState(initialOpen);
  // The finished lists as read when their tab was opened: undefined while reading, null when unreadable.
  const [finished, setFinished] = useState<Record<'acknowledged' | 'closed', AlertItem[] | null | undefined>>({ acknowledged: undefined, closed: undefined });
  const [tab, setTab] = useState<Tab>('open');
  const [error, setError] = useState<string | null>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ open: null, acknowledged: null, closed: null });
  const baseId = useId();
  const labelOf = (name: Tab) => (name === 'open' ? `Open (${open.length})` : name === 'acknowledged' ? 'Acknowledged' : 'Closed');

  useEffect(() => {
    if (tab === 'open') return undefined;
    let live = true;
    // A read of a list the back end keeps: it is read again each time its tab is opened.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFinished((current) => ({ ...current, [tab]: undefined }));
    void bffRequest<{ items: AlertItem[] }>(`/api/bff/exec/alerts?state=${tab}`).then((result) => {
      if (live) setFinished((current) => ({ ...current, [tab]: result.ok ? result.data.items : null }));
    });
    return () => {
      live = false;
    };
  }, [tab]);

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
    const result = await bffRequest(`/api/bff/exec/alerts/${encodeURIComponent(item.id)}/acknowledge`, { method: 'POST' });
    if (result.ok) return;
    setOpen((current) => [item, ...current]);
    setError(ACK_FAILED);
  };

  const card = (item: AlertItem, actions: boolean) => (
    <article key={item.id} className={styles.card} aria-label={alertTitle(item)}>
      <h2 className={styles.cardTitle}>{alertTitle(item)}</h2>
      {item.detail !== null ? <p>{item.detail}</p> : null}
      <p className={styles.footer}>
        {item.state === 'acknowledged' && item.acknowledgedAt !== null
          ? `Acknowledged at ${alertTime(item.acknowledgedAt)} · alerted ${alertTime(item.raisedAt)}`
          : `${STATE_WORD[item.state]} · alerted ${alertTime(item.raisedAt)}`}
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
      {(['acknowledged', 'closed'] as const).map((name) => {
        const list = finished[name];
        return (
          <div key={name} role="tabpanel" id={`${baseId}-${name}-panel`} aria-labelledby={`${baseId}-${name}-tab`} hidden={tab !== name}>
            {tab !== name ? null : list === undefined ? (
              <p>Loading.</p>
            ) : list === null ? (
              <p role="alert" className={styles.error}>{`${name === 'acknowledged' ? 'Acknowledged' : 'Closed'} alerts could not be read. Try again shortly.`}</p>
            ) : list.length === 0 ? (
              <p>{name === 'acknowledged' ? 'Nothing acknowledged.' : 'Nothing closed.'}</p>
            ) : (
              list.map((item) => card(item, false))
            )}
          </div>
        );
      })}
    </div>
  );
}
