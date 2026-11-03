'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { NumberStepper } from '@/components/reporter/parts/NumberStepper';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag } from '@/components/ui/StatusTag';
import { splitUnitLabel } from '@/lib/links/model';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from './GroupedUpdate.module.css';
import { type ServiceRow, readRows, stateText } from './serviceState';

// The grouped update (W38, artboard B6): every service due together on one phone, one screen. One primary
// "Both still right" confirms the services still waiting; each service also has its own Still right and
// Change, and Change opens the number stepper inside that service's card. A row is answered on its own: a
// partial answer never confirms the others (they stay "Waiting"), and a row the back end would not take
// says so on its own line. (The notifications strip and the tab bar are the frame's, ReporterAppFrame.)

type Result = { serviceId: string; result: string; at?: string };
type Answered = { value: number | null; at: string };
type Changing = { id: string; low: number; high: number; value: number | null; flagged: number | null };

const COULD_NOT_RECORD = 'We could not record that. Try again.';

export function GroupedUpdate() {
  const router = useRouter();
  const [rows, setRows] = useState<ServiceRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [answered, setAnswered] = useState<Record<string, Answered>>({});
  const [changing, setChanging] = useState<Changing | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [lines, setLines] = useState<Record<string, string>>({});

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/services').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const list = reply.status === 200 ? readRows(reply.body) : null;
      if (list !== null) setRows(list);
      else setFailed(true);
      return undefined;
    });
    return () => {
      live = false;
    };
  }, [router]);

  if (failed) {
    return (
      <main className={styles.page}>
        <Banner tone="warning" title="We could not load your services. Try again shortly." />
      </main>
    );
  }
  if (rows === null) {
    return (
      <main className={styles.page}>
        <Loading label="Loading your services.">
          <SkeletonRows count={3} />
        </Loading>
      </main>
    );
  }

  const due = rows.filter((row) => row.state === 'due');
  const waiting = due.filter((row) => answered[row.id] === undefined);
  const anyAnswered = Object.keys(answered).length > 0;

  const setLine = (id: string, text: string | null) =>
    setLines((current) => {
      const next = { ...current };
      if (text === null) delete next[id];
      else next[id] = text;
      return next;
    });

  const send = async (targets: ServiceRow[]) => {
    setBusy(true);
    setNotice(null);
    const reply = await bffRequest('/api/bff/reporter/reports/batch', {
      method: 'POST',
      body: { items: targets.map((row) => ({ serviceId: row.id, kind: 'confirm' as const })) },
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    });
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const results = (reply.body as { results?: Result[] } | undefined)?.results;
    if (reply.status !== 200 || !Array.isArray(results)) return setNotice(COULD_NOT_RECORD);
    const nextAnswered = { ...answered };
    const nextLines = { ...lines };
    for (const row of targets) {
      const item = results.find((r) => r.serviceId === row.id);
      delete nextLines[row.id];
      if (item?.result === 'recorded' && row.recordedValue !== null) nextAnswered[row.id] = { value: row.recordedValue, at: item.at ?? '' };
      // A confirm the back end would not take (an old figure, a limit) is not shown as done.
      else if (item?.result === 'sendNumber' || item?.result === 'confirmLimit') nextLines[row.id] = `${row.name} needs its number. Use Change to send it.`;
      else nextLines[row.id] = COULD_NOT_RECORD;
    }
    setAnswered(nextAnswered);
    setLines(nextLines);
    return undefined;
  };

  const openChange = async (row: ServiceRow) => {
    setBusy(true);
    setLine(row.id, null);
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(row.id)}/prompt`);
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const route = reply.body as { low?: unknown; high?: unknown } | undefined;
    if (reply.status !== 200 || typeof route?.low !== 'number' || typeof route.high !== 'number') return setLine(row.id, 'We could not open that service. Try again.');
    return setChanging({ id: row.id, low: route.low, high: route.high, value: null, flagged: null });
  };

  const answerChange = async (row: ServiceRow, kind: 'number' | 'closed') => {
    if (changing === null || changing.id !== row.id) return;
    const { value, flagged } = changing;
    if (kind === 'number' && value === null) return;
    setBusy(true);
    setLine(row.id, null);
    const body: Record<string, unknown> = kind === 'number' ? { kind, value } : { kind };
    if (kind === 'number' && flagged === value) body.confirmOutOfRange = true;
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(row.id)}/report`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    });
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const recorded = reply.body as { result?: string; recordedAt?: string; low?: number; high?: number } | undefined;
    if (reply.status === 200 && recorded?.result === 'recorded') {
      setAnswered((current) => ({ ...current, [row.id]: { value: kind === 'number' ? value : null, at: recorded.recordedAt ?? '' } }));
      return setChanging(null);
    }
    if (reply.status === 200 && recorded?.result === 'outOfRange' && kind === 'number') {
      setChanging({ ...changing, flagged: value });
      const low = typeof recorded.low === 'number' ? recorded.low : changing.low;
      const high = typeof recorded.high === 'number' ? recorded.high : changing.high;
      return setLine(row.id, `That is outside your usual range (${low} to ${high}). Send it again to confirm.`);
    }
    return setLine(row.id, COULD_NOT_RECORD);
  };

  const bothValues = waiting.map((row) => String(row.recordedValue ?? '–')).join(' and ');
  const earliest = due.map((row) => row.replyBy).filter((v): v is string => typeof v === 'string').sort()[0];
  const earliestClock = clock(earliest);

  return (
    <main className={styles.page}>
      <div className={styles.head}>
        <h1 className={styles.title}>{`${rows.length} services`}</h1>
        {earliestClock !== '' ? (
          <span className={styles.by}>
            <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M10 5.5V10l3 2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            {`By ${earliestClock}`}
          </span>
        ) : null}
      </div>
      {waiting.length > 1 ? (
        <div className={styles.both}>
          <Button variant="primary" busy={busy} dataEl="REP-MULTI-BOTH-BTN" onClick={() => void send(waiting)}>
            {`Both still right (${bothValues})`}
          </Button>
        </div>
      ) : null}
      <ol className={styles.list}>
        {rows.map((row) => {
          const done = answered[row.id];
          const open = changing !== null && changing.id === row.id ? changing : null;
          const line = lines[row.id];
          const { noun } = splitUnitLabel(row.unitLabel);
          return (
            <li key={row.id} className={styles.card} data-state={row.state}>
              <div className={styles.top}>
                <h2 className={styles.name}>{row.name}</h2>
                {row.at !== null && clock(row.at) !== '' ? <span className={styles.at}>{`at ${clock(row.at)}`}</span> : null}
              </div>
              {row.recordedValue !== null && !(done !== undefined && done.value === null) ? (
                <p className={styles.figureRow}>
                  <span className={styles.figure}>{done !== undefined && done.value !== null ? done.value : row.recordedValue}</span>
                  <span className={styles.unit}>{row.unitLabel}</span>
                </p>
              ) : null}
              {done !== undefined ? (
                <p className={styles.state}>
                  <StatusTag variant={done.value === null ? 'closed' : 'confirmed'}>{`${done.value === null ? 'Closed' : 'Confirmed'} ${clock(done.at)}`}</StatusTag>
                </p>
              ) : row.state === 'due' ? (
                <>
                  {anyAnswered && open === null ? (
                    <p className={styles.state}>
                      <StatusTag variant="waiting">Waiting</StatusTag>
                    </p>
                  ) : null}
                  {open === null ? (
                    <div className={styles.actions}>
                      <Button variant="secondary" busy={busy} dataEl={`REP-MULTI-STILLRIGHT-${row.id}`} onClick={() => void send([row])}>
                        Still right
                      </Button>
                      <Button variant="neutral" busy={busy} dataEl={`REP-MULTI-CHANGE-${row.id}`} onClick={() => void openChange(row)}>
                        Change
                      </Button>
                    </div>
                  ) : (
                    <div className={styles.change}>
                      <NumberStepper
                        label={`New number for ${row.name}`}
                        value={open.value}
                        onChange={(value) => setChanging({ ...open, value })}
                        unit={noun}
                        usualMin={open.low}
                        usualMax={open.high}
                        dataEl={`REP-MULTI-STEPPER-${row.id}`}
                      />
                      <div className={styles.send}>
                        <Button variant="primary" busy={busy} disabled={open.value === null} dataEl={`REP-MULTI-SEND-${row.id}`} onClick={() => void answerChange(row, 'number')}>
                          Send new number
                        </Button>
                      </div>
                      <div className={styles.secondaryActions}>
                        <Button variant="neutral" busy={busy} dataEl={`REP-MULTI-CLOSED-${row.id}`} onClick={() => void answerChange(row, 'closed')}>
                          We are closed to referrals
                        </Button>
                        <Button variant="neutral" busy={busy} dataEl={`REP-MULTI-CANCEL-${row.id}`} onClick={() => setChanging(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <p className={styles.state}>{stateText(row)}</p>
              )}
              {line !== undefined ? <p className={styles.line}>{line}</p> : null}
            </li>
          );
        })}
      </ol>
      <ul className={styles.thanks}>
        {rows
          .filter((row) => answered[row.id] !== undefined)
          .map((row) => {
            const item = answered[row.id];
            return <li key={`thanks-${row.id}`}>{item.value === null ? `${row.name} closed · ${clock(item.at)}` : `${row.name} ${item.value} ${row.unitLabel} · ${clock(item.at)}`}</li>;
          })}
      </ul>
      <p className={styles.note}>Each service is confirmed on its own line in the record.</p>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
    </main>
  );
}
