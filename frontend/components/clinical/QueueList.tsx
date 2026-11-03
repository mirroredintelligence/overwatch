'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { bffRequest } from '@/lib/bff/browser';
import { durationText, londonTime } from '@/lib/board/format';
import { ADVICE_LABELS } from '@/lib/clinical/advice';
import { summaryLine, urgencyText, WHY_TEXT, type QueueItem } from '@/lib/clinical/queue';
import styles from './Clinical.module.css';

// The clinical lists (W44, ClinicalAdvisor screen 4): Waiting, Mine and Done, each the back end's own
// list. Waiting refreshes every 15 seconds, and so does the tab being shown. Taking a request is the
// only way to hold it; once taken no one else can, so a refusal says so and refreshes. A request whose
// case could not be read is not offered to take: it could not be answered from here (DEC-855).

export const REFRESH_MS = 15_000;
export const TAKEN_ELSEWHERE = 'Someone else has taken this request.';
const TAKE_NOTE = 'Once you take a request, no one else can. It returns to the queue if you do not act in 10 minutes.';
const READ_FAILED = 'The queue could not be read. Try again shortly.';
const CASE_UNREADABLE = 'The case could not be read, so this request cannot be answered here.';

type Tab = 'waiting' | 'mine' | 'done';
const TABS: readonly Tab[] = ['waiting', 'mine', 'done'];

function waitingFor(requestedAt: string, now: number): string {
  const minutes = Math.max(1, Math.floor((now - Date.parse(requestedAt)) / 60_000));
  return `Waiting ${durationText(minutes)}`;
}

/** The advisor's own status, as the page gives it (the heading's neighbour, not the top bar). */
export function QueueList({ status = null }: { status?: string | null }) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('waiting');
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [waitingCount, setWaitingCount] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<number>(0);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ waiting: null, mine: null, done: null });
  const shown = useRef<Tab>('waiting');

  const load = useCallback(async (which: Tab) => {
    const result = await bffRequest<{ items: QueueItem[] }>(`/api/bff/clinical/requests?tab=${which}`);
    if (which === 'waiting' && result.ok) setWaitingCount(result.data.items.length);
    // An answer for a tab that is no longer shown is dropped.
    if (shown.current !== which) return;
    if (!result.ok) {
      setFailed(true);
      return;
    }
    setFailed(false);
    setItems(result.data.items);
    setLoadedAt(Date.now());
  }, []);

  useEffect(() => {
    // A polling source: the shown list is read from the back end on mount, on a tab change and every
    // 15 seconds. It is cleared first so one tab's requests are never shown under another's name.
    shown.current = tab;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setItems(null);
    void load(tab);
    const timer = setInterval(() => void load(tab), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, tab]);

  const select = (next: Tab) => {
    setTab(next);
    setMessage(null);
    tabRefs.current[next]?.focus();
  };

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = TABS.indexOf(tab);
    if (event.key === 'ArrowRight') select(TABS[(index + 1) % TABS.length] ?? 'waiting');
    else if (event.key === 'ArrowLeft') select(TABS[(index + TABS.length - 1) % TABS.length] ?? 'waiting');
    else if (event.key === 'Home') select('waiting');
    else if (event.key === 'End') select('done');
    else return;
    event.preventDefault();
  };

  const take = async (item: QueueItem) => {
    setBusyId(item.id);
    setMessage(null);
    const result = await bffRequest(`/api/bff/clinical/requests/${encodeURIComponent(item.id)}/take`, { method: 'POST' });
    setBusyId(null);
    if (!result.ok) {
      setMessage(result.status === 409 ? TAKEN_ELSEWHERE : 'Could not take this request. Try again.');
      void load(tab);
      router.refresh();
      return;
    }
    // The case page reads the request itself: the address carries the request's id and nothing else.
    router.push(`/clinical/requests/${encodeURIComponent(item.id)}`);
  };

  const label = (name: Tab) => (name === 'waiting' ? (waitingCount === null ? 'Waiting' : `Waiting (${waitingCount})`) : name === 'mine' ? 'Mine' : 'Done');

  const card = (item: QueueItem) => {
    const line = summaryLine(item.glance);
    const now = item.urgency === 'now';
    return (
      <article key={item.id} className={`${styles.card} ${styles.request} ${now ? styles.requestNow : ''}`} aria-label={`${urgencyText(item.urgency)} · ${WHY_TEXT[item.why] ?? item.why}`}>
        <div className={styles.urgency}>
          <span className={`${styles.tag} ${now ? styles.tagSolid : styles.tagOutline}`} data-tone={now ? 'solid' : 'outline'}>
            <span className={styles.tagDot} aria-hidden="true" />
            {urgencyText(item.urgency)}
          </span>
          {tab === 'waiting' ? <p className={styles.wait}>{waitingFor(item.requestedAt, loadedAt)}</p> : null}
        </div>
        <div className={styles.body}>
          {line !== null ? <p className={styles.title}>{line}</p> : <p className={styles.title}>{CASE_UNREADABLE}</p>}
          <p className={styles.why}>{WHY_TEXT[item.why] ?? item.why}</p>
          {tab === 'mine' && item.returnsAt !== null ? <p className={styles.requestNote}>{`Returns to the queue at ${londonTime(item.returnsAt)}`}</p> : null}
          {tab === 'done' && item.advice !== null ? (
            <p className={styles.requestNote}>{`Advice given: ${item.advice.choice in ADVICE_LABELS ? ADVICE_LABELS[item.advice.choice as keyof typeof ADVICE_LABELS] : item.advice.choice}`}</p>
          ) : null}
        </div>
        {tab === 'waiting' && item.glance !== null ? (
          <Button variant={now ? 'primary' : 'secondary'} busy={busyId === item.id} onClick={() => take(item)} dataEl="CLIN-QUEUE-TAKE-BTN">
            Take it
          </Button>
        ) : null}
        {tab === 'mine' ? (
          <Link href={`/clinical/requests/${encodeURIComponent(item.id)}`} className={styles.take} data-el="CLIN-QUEUE-OPEN-LINK">
            Open
          </Link>
        ) : null}
      </article>
    );
  };

  return (
    <div className={styles.queue}>
      <div className={styles.queueHead}>
        <div className={styles.titleGroup}>
          <h1 className={styles.queueHeading}>Requests</h1>
          {status !== null ? <span className={styles.status}>{status}</span> : null}
        </div>
        <div role="tablist" aria-label="Requests" className={styles.tabs}>
          {TABS.map((name) => (
            <button
              key={name}
              ref={(node) => {
                tabRefs.current[name] = node;
              }}
              type="button"
              role="tab"
              id={`clin-${name}-tab`}
              aria-selected={tab === name}
              aria-controls="clin-panel"
              tabIndex={tab === name ? 0 : -1}
              onClick={() => select(name)}
              onKeyDown={onTabKey}
              className={styles.tab}
              data-el={`CLIN-QUEUE-TAB-${name.toUpperCase()}`}
            >
              {label(name)}
            </button>
          ))}
        </div>
      </div>
      <div role="tabpanel" id="clin-panel" aria-labelledby={`clin-${tab}-tab`} className={styles.list}>
        {tab === 'waiting' ? (
          <p className={styles.oneAtATime}>
            <strong>One at a time</strong>
            <span>{TAKE_NOTE}</span>
          </p>
        ) : null}
        {message ? <p role="alert" className={styles.error}>{message}</p> : null}
        {failed ? <p role="alert" className={styles.error}>{READ_FAILED}</p> : null}
        {items === null && !failed ? (
          <Loading label="Loading the requests.">
            <SkeletonRows count={3} />
          </Loading>
        ) : null}
        {items !== null && items.length === 0 && !failed ? (
          <p>{tab === 'waiting' ? 'No requests are waiting.' : tab === 'mine' ? 'You hold no requests.' : 'You have not given advice yet.'}</p>
        ) : null}
        {(items ?? []).map(card)}
      </div>
    </div>
  );
}
