'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { type Answer, CapacityResponseForm, type Prompt } from '@/components/reporter/CapacityResponseForm';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';
import { type ServiceRow, stateText } from './serviceState';

// The grouped update (W38): every service due together on one phone, one screen. A row is answered
// on its own; a partial answer never confirms the others, which stay "Waiting". Changing one row
// opens that service's own form with a banner naming it.

type Result = { serviceId: string; result: string; at?: string };

export function GroupedUpdate() {
  const router = useRouter();
  const [rows, setRows] = useState<ServiceRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [answered, setAnswered] = useState<Record<string, { value: number; at: string }>>({});
  const [changing, setChanging] = useState<ServiceRow | null>(null);
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/services').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const list = (reply.body as { services?: ServiceRow[] } | undefined)?.services;
      if (reply.status === 200 && Array.isArray(list)) setRows(list);
      else setFailed(true);
    });
    return () => {
      live = false;
    };
  }, [router]);

  if (failed) return <main className={styles.page}><p>We could not load your services. Try again shortly.</p></main>;
  if (rows === null) return <main className={styles.page}><p role="status">Opening your services</p></main>;

  const due = rows.filter((row) => row.state === 'due');
  const anyAnswered = Object.keys(answered).length > 0;

  const send = async (items: { serviceId: string; kind: 'confirm' }[]) => {
    setBusy(true);
    setNotice(null);
    const reply = await bffRequest('/api/bff/reporter/reports/batch', { method: 'POST', body: { items } });
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const results = (reply.body as { results?: Result[] } | undefined)?.results;
    if (reply.status !== 200 || !Array.isArray(results)) return setNotice('We could not record that. Try again.');
    const next = { ...answered };
    for (const item of results) {
      const row = rows.find((r) => r.id === item.serviceId);
      if (item.result === 'recorded' && row !== undefined && row.recordedValue !== null) {
        next[row.id] = { value: row.recordedValue, at: item.at ?? '' };
      }
    }
    return setAnswered(next);
  };

  const openChange = async (row: ServiceRow) => {
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(row.id)}/prompt`);
    if (reply.status !== 200) return setNotice('We could not open that service. Try again.');
    const route = reply.body as Prompt;
    setPrompt({ ...route, service: row.name, unitLabel: row.unitLabel, recordedValue: row.recordedValue, asOf: row.at });
    setChanging(row);
    return undefined;
  };

  const answerChange = async (answer: Answer) => {
    if (changing === null || prompt === null) return;
    setBusy(true);
    setNotice(null);
    const body = answer.kind === 'number' ? { kind: 'number', value: answer.value } : { kind: answer.kind };
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(changing.id)}/report`, { method: 'POST', body });
    setBusy(false);
    const recorded = reply.body as { result?: string; recordedAt?: string } | undefined;
    if (reply.status === 200 && recorded?.result === 'recorded') {
      const value = answer.kind === 'number' ? answer.value : (changing.recordedValue ?? 0);
      setAnswered((current) => ({ ...current, [changing.id]: { value, at: recorded.recordedAt ?? '' } }));
      setChanging(null);
      setPrompt(null);
      return;
    }
    setNotice('We could not record that. Try again.');
  };

  if (changing !== null && prompt !== null) {
    // The banner counts the phone's due services by name, so UCR East reads "1 of 2" (as on the
    // artboard). The "Both still right" label keeps the service letters' order.
    const byName = [...due].sort((a, b) => a.name.localeCompare(b.name));
    const position = byName.findIndex((row) => row.id === changing.id) + 1;
    return (
      <CapacityResponseForm
        prompt={prompt}
        busy={busy}
        notice={notice}
        confirmAllowed
        serviceBanner={{ name: changing.name, position, total: due.length }}
        onAnswer={(answer) => void answerChange(answer)}
      />
    );
  }

  const bothValues = due.map((row) => String(row.recordedValue ?? '–')).join(' and ');
  const earliest = due.map((row) => row.replyBy).filter((v): v is string => typeof v === 'string').sort()[0];

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${rows.length} services`}</h1>
      {earliest !== undefined ? <p>{`Update by ${earliest}`}</p> : null}
      {due.length > 1 ? (
        <Button
          variant="primary"
          busy={busy}
          dataEl="REP-MULTI-BOTH-BTN"
          onClick={() => void send(due.map((row) => ({ serviceId: row.id, kind: 'confirm' as const })))}
        >
          {`Both still right (${bothValues})`}
        </Button>
      ) : null}
      <ol className={styles.steps}>
        {rows.map((row) => {
          const done = answered[row.id];
          return (
            <li key={row.id}>
              <strong>{row.name}</strong>
              {done !== undefined ? (
                <p>{`Confirmed ${done.at}`}</p>
              ) : row.state === 'due' ? (
                <>
                  <p>{anyAnswered ? 'Waiting' : `We have ${row.recordedValue ?? 0} ${row.unitLabel}. Still right?`}</p>
                  <Button variant="neutral" busy={busy} dataEl={`REP-MULTI-STILLRIGHT-${row.id}`} onClick={() => void send([{ serviceId: row.id, kind: 'confirm' }])}>
                    Still right
                  </Button>
                  <Button variant="neutral" busy={busy} dataEl={`REP-MULTI-CHANGE-${row.id}`} onClick={() => void openChange(row)}>
                    Change
                  </Button>
                </>
              ) : (
                <p>{stateText(row)}</p>
              )}
            </li>
          );
        })}
      </ol>
      <ul>
        {rows
          .filter((row) => answered[row.id] !== undefined)
          .map((row) => (
            <li key={`thanks-${row.id}`}>{`${row.name} ${answered[row.id].value} ${row.unitLabel} · ${answered[row.id].at}`}</li>
          ))}
      </ul>
      {anyAnswered ? <p>Each service is confirmed separately in the record.</p> : <p>Each service is confirmed separately in the record.</p>}
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
    </main>
  );
}
