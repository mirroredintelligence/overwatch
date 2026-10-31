'use client';

import { useState } from 'react';
import { useAdminRead } from '@/lib/tenantAdmin/browser';
import type { parseLog } from '@/lib/tenantAdmin/views';
import { plainAction, roleWord, whenText } from '@/lib/tenantAdmin/words';
import styles from './admin.module.css';

// "Who has accessed your organisation" (TEN-076, TEN-084): what the platform's own people did in this
// organisation, read from the organisation's own chain. The role and the step in plain words and the
// reference it was under; never a name or the opaque reference of the person (the BFF has dropped it).

type Log = ReturnType<typeof parseLog>;
const WINDOWS: readonly [number, string][] = [
  [30, '30 days'],
  [90, '90 days'],
  [400, '400 days'],
];

export function AccessLog() {
  const [days, setDays] = useState(90);
  const { state } = useAdminRead<Log>(`/api/bff/tenant/access-log?days=${days}`);
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Who has accessed your organisation</h1>
      <p className={styles.lede}>This is what the platform’s own people did in your organisation. You cannot change it.</p>
      <div className={styles.selectLabel}>
        <label htmlFor="log-days">Show the last</label>
        <select id="log-days" className={styles.select} value={String(days)} onChange={(event) => setDays(Number(event.target.value))}>
          {WINDOWS.map(([value, word]) => (
            <option key={value} value={String(value)}>
              {word}
            </option>
          ))}
        </select>
      </div>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the access log.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the access log.
        </p>
      ) : null}
      {state.status === 'ok' ? <Entries entries={state.data.entries} /> : null}
    </main>
  );
}

function Entries({ entries }: { entries: Log['entries'] }) {
  if (entries.length === 0) return <p className={styles.text}>Nobody from the platform has accessed your organisation in this time.</p>;
  return (
    <>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption>Access by the platform’s own people</caption>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Who</th>
              <th scope="col">What happened</th>
              <th scope="col">Reference</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={`${entry.at}-${index}`}>
                <td>{whenText(entry.at)}</td>
                <td>{roleWord(entry.role)}</td>
                <td>{plainAction(entry.useCase)}</td>
                <td>{entry.entityIds.length === 0 ? '-' : entry.entityIds.join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.muted}>{`${entries.length} ${entries.length === 1 ? 'step' : 'steps'} shown. The list shows at most 200, newest first.`}</p>
    </>
  );
}
