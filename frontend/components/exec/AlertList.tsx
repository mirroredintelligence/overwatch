'use client';

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import { bffRequest } from '@/lib/bff/browser';
import { alertTime, alertTitle, type AlertItem } from '@/lib/exec/alerts';
import { AlertDetail, alertTag } from './AlertDetail';
import styles from './AlertList.module.css';

// The executive's alerts (W40, ExecApp1 screen 4; boards/planning/PAlerts, PH2). Tabs: Open, Acknowledged, Closed.
// Open comes with the page; Acknowledged and Closed are read from the back end's own lists when their tab is
// opened (W7A, DEC-775), so they hold every alert, not only this visit's. The selected alert is shown beside the
// list, where it can be acknowledged, called about or snoozed in place. An acknowledgement moves its card out of
// Open at once; a failure moves it back and says so. A list that could not be read is said, never shown as empty.

type Tab = 'open' | 'acknowledged' | 'closed';
const TABS: readonly Tab[] = ['open', 'acknowledged', 'closed'];
export const ACK_FAILED = 'Could not acknowledge. Try again.';

export function AlertList({ open: initialOpen, coordinationPhone = null }: { open: AlertItem[]; coordinationPhone?: string | null }) {
  const [open, setOpen] = useState(initialOpen);
  // The finished lists as read when their tab was opened: undefined while reading, null when unreadable.
  const [finished, setFinished] = useState<Record<'acknowledged' | 'closed', AlertItem[] | null | undefined>>({ acknowledged: undefined, closed: undefined });
  const [tab, setTab] = useState<Tab>('open');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ open: null, acknowledged: null, closed: null });
  const baseId = useId();
  const acknowledgedList = finished.acknowledged;
  const labelOf = (name: Tab) =>
    name === 'open' ? `Open ${open.length}` : name === 'acknowledged' ? (Array.isArray(acknowledgedList) ? `Acknowledged ${acknowledgedList.length}` : 'Acknowledged') : 'Closed';

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
    setNotice(null);
    setOpen((current) => current.filter((a) => a.id !== item.id));
    const result = await bffRequest(`/api/bff/exec/alerts/${encodeURIComponent(item.id)}/acknowledge`, { method: 'POST' });
    if (result.ok) return;
    setOpen((current) => [item, ...current]);
    setError(ACK_FAILED);
  };

  // The pane's own acknowledgement has been taken by the back end: the card leaves Open and the pane moves on.
  const acknowledgedInPane = (id: string) => {
    const item = open.find((a) => a.id === id);
    setError(null);
    setNotice(item ? `${alertTitle(item)} acknowledged.` : 'Acknowledged.');
    setOpen((current) => current.filter((a) => a.id !== id));
  };

  const shown: AlertItem[] = tab === 'open' ? open : (finished[tab] ?? []);
  const selected = shown.find((item) => item.id === selectedId) ?? shown[0];

  const card = (item: AlertItem, actions: boolean) => {
    const tag = alertTag(item);
    const waiting = item.state === 'new' || item.state === 'escalated';
    return (
      <article key={item.id} className={styles.card} aria-label={alertTitle(item)} data-selected={selected?.id === item.id}>
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>
            <button type="button" className={styles.pick} aria-pressed={selected?.id === item.id} onClick={() => setSelectedId(item.id)}>
              {alertTitle(item)}
            </button>
          </h2>
          <StatusTag variant={tag.variant}>{tag.word}</StatusTag>
        </div>
        {item.detail !== null ? <p className={styles.line}>{item.detail}</p> : null}
        <p className={styles.footer}>
          {item.state === 'acknowledged' && item.acknowledgedAt !== null
            ? `Acknowledged by you ${alertTime(item.acknowledgedAt)} · alerted ${alertTime(item.raisedAt)}`
            : waiting && item.escalatesAt !== null
              ? `Alerted ${alertTime(item.raisedAt)} · deputy alerted at ${alertTime(item.escalatesAt)} if not acknowledged`
              : `Alerted ${alertTime(item.raisedAt)}`}
        </p>
        {actions ? (
          <div className={styles.cardActions}>
            <Button variant="primary" onClick={() => acknowledge(item)} dataEl="EXEC-ALERT-ACK-BTN">Acknowledge</Button>
            <Button variant="secondary" href={`/planning/alerts/${encodeURIComponent(item.id)}`} dataEl="EXEC-ALERT-OPEN-BTN">Open</Button>
          </div>
        ) : null}
      </article>
    );
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.heading}>Alerts</h1>
      <div className={styles.layout}>
        <section className={styles.list} aria-label="Alert list">
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
          {notice ? <p role="status" className={styles.status}>{notice}</p> : null}

          <div role="tabpanel" id={`${baseId}-open-panel`} aria-labelledby={`${baseId}-open-tab`} hidden={tab !== 'open'} className={styles.list}>
            {open.length === 0 ? <p>No open alerts.</p> : open.map((item) => card(item, true))}
          </div>
          {(['acknowledged', 'closed'] as const).map((name) => {
            const list = finished[name];
            return (
              <div key={name} role="tabpanel" id={`${baseId}-${name}-panel`} aria-labelledby={`${baseId}-${name}-tab`} hidden={tab !== name} className={styles.list}>
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

          <p className={styles.note}>Acknowledging tells others it is being handled. It does not change the board. Alerts never include patient information.</p>
        </section>

        <div className={styles.pane}>
          {selected ? <AlertDetail key={selected.id} alert={selected} layout="pane" coordinationPhone={coordinationPhone} onAcknowledged={acknowledgedInPane} /> : null}
        </div>
      </div>
    </div>
  );
}
