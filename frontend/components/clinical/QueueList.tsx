'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { durationText } from '@/lib/board/format';
import { WHY_TEXT, urgencyText, type QueueItem } from '@/lib/clinical/queue';
import styles from '@/components/exec/Exec.module.css';

// The queue of waiting requests (W44, ClinicalAdvisor screen 4). It refreshes every 15 seconds. Taking a
// request is the only way to open it; once taken no one else can, so a refusal says so and refreshes.

export const REFRESH_MS = 15_000;
export const TAKEN_ELSEWHERE = 'Someone else has taken this request.';
const TAKE_NOTE = 'Once you take a request, no one else can. It returns to the queue if you do not act in 10 minutes.';

function waitingFor(requestedAt: string, now: number): string {
  const minutes = Math.max(1, Math.floor((now - Date.parse(requestedAt)) / 60_000));
  return `Waiting ${durationText(minutes)}`;
}

export function QueueList() {
  const router = useRouter();
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<number>(0);

  const load = useCallback(async () => {
    const result = await bffRequest<{ items: QueueItem[] }>('/api/bff/clinical/requests?tab=waiting');
    if (!result.ok) return;
    setItems(result.data.items);
    setLoadedAt(Date.now());
  }, []);

  useEffect(() => {
    // A polling source: the queue is read from the back end on mount and every 15 seconds.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const take = async (item: QueueItem) => {
    setBusyId(item.id);
    setMessage(null);
    const result = await bffRequest(`/api/bff/clinical/requests/${encodeURIComponent(item.id)}/take`, { method: 'POST' });
    setBusyId(null);
    if (!result.ok) {
      setMessage(result.status === 409 ? TAKEN_ELSEWHERE : 'Could not take this request. Try again.');
      void load();
      router.refresh();
      return;
    }
    const query = new URLSearchParams({ urgency: item.urgency, why: item.why, case: item.caseId });
    router.push(`/clinical/requests/${encodeURIComponent(item.id)}?${query.toString()}`);
  };

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>{`Waiting (${items?.length ?? 0})`}</h1>
      <p className={styles.footer}>{TAKE_NOTE}</p>
      {message ? <p role="alert" className={styles.error}>{message}</p> : null}
      {items === null ? <p>Loading the queue.</p> : null}
      {items !== null && items.length === 0 ? <p>No requests are waiting.</p> : null}
      {(items ?? []).map((item) => (
        <article key={item.id} className={styles.card} aria-label={`${urgencyText(item.urgency)} · ${WHY_TEXT[item.why] ?? item.why}`}>
          <p className={styles.cardTitle}>{urgencyText(item.urgency)}</p>
          <p>{waitingFor(item.requestedAt, loadedAt)}</p>
          <p>{WHY_TEXT[item.why] ?? item.why}</p>
          <div className={styles.actions}>
            <Button variant="primary" busy={busyId === item.id} onClick={() => take(item)} dataEl="CLIN-QUEUE-TAKE-BTN">
              Take it
            </Button>
          </div>
        </article>
      ))}
      <p className={styles.footer}>Mine and Done are not available yet.</p>
    </div>
  );
}
