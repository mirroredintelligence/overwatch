'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import styles from './Console.module.css';

// Find a session (W48): open one with a support code, or search the aggregates and session ids.
// Search shows counts and ids only; the timeline is opened with a code or an approved ticket.

const ROLE_CHIPS = ['advisor', 'lead', 'clinical', 'reporter'] as const;

type SearchItem = {
  sessionId: string;
  role: string;
  device: string;
  release: string;
  started: string;
  eventCount: number;
  frictionCount: number;
  errorCount: number;
};

const NO_ACCESS = 'You do not have access to the console.';
const CODE_REFUSED = 'That code is not valid or has expired.';

async function readJson<T>(response: Response): Promise<T | null> {
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export function FindSession() {
  const router = useRouter();
  const [code, setCode] = useState('');
  const [openError, setOpenError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  const [sessionId, setSessionId] = useState('');
  const [traceId, setTraceId] = useState('');
  const [reference, setReference] = useState('');
  const [release, setRelease] = useState('');
  const [roles, setRoles] = useState<string[]>([]);
  const [items, setItems] = useState<SearchItem[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  async function openWithCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOpening(true);
    setOpenError(null);
    try {
      const response = await fetch('/api/bff/console/sessions/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ supportCode: code }),
        credentials: 'same-origin',
      });
      if (response.status === 403) {
        setOpenError(CODE_REFUSED);
        return;
      }
      const body = await readJson<{ sessionId?: string }>(response);
      if (!response.ok || !body?.sessionId) {
        setOpenError('The session could not be opened. Try again.');
        return;
      }
      router.push(`/console/session/${encodeURIComponent(body.sessionId)}`);
    } catch {
      setOpenError('The session could not be opened. Try again.');
    } finally {
      setOpening(false);
    }
  }

  async function search() {
    setSearchError(null);
    const params = new URLSearchParams();
    if (sessionId) params.set('sessionId', sessionId);
    if (traceId) params.set('traceId', traceId);
    if (reference) params.set('reference', reference);
    if (release) params.set('release', release);
    for (const role of roles) params.append('role', role);
    try {
      const response = await fetch(`/api/bff/console/sessions?${params.toString()}`, {
        credentials: 'same-origin',
      });
      if (response.status === 403) {
        setSearchError(NO_ACCESS);
        setItems(null);
        return;
      }
      if (!response.ok) {
        setSearchError('The search could not be run. Try again.');
        setItems(null);
        return;
      }
      const body = await readJson<{ items: SearchItem[] }>(response);
      setItems(body?.items ?? []);
    } catch {
      setSearchError('The search could not be run. Try again.');
    }
  }

  function toggleRole(role: string, next: boolean) {
    setRoles((current) => (next ? [...current, role] : current.filter((item) => item !== role)));
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Find a session</h1>

      <section className={styles.section} aria-labelledby="console-open-heading">
        <h2 id="console-open-heading" className={styles.heading}>Open one session</h2>
        <p className={styles.help}>
          Opening one session needs a support code the person shared, or an approved ticket. Every open is logged and
          shown to the person.
        </p>
        <form className={styles.form} onSubmit={openWithCode}>
          <div className={styles.field}>
            <label htmlFor="console-code">Support code</label>
            <input
              id="console-code"
              className={styles.input}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              autoComplete="off"
              maxLength={32}
            />
          </div>
          <Button variant="primary" type="submit" busy={opening} dataEl="CON-FIND-OPEN-BTN">
            Open session
          </Button>
        </form>
        {openError !== null && <p role="alert" className={styles.alert}>{openError}</p>}
      </section>

      <section className={styles.section} aria-labelledby="console-search-heading">
        <h2 id="console-search-heading" className={styles.heading}>Or search</h2>
        <p className={styles.help}>Search shows aggregates and session ids only. Opening a timeline asks for a support code or a ticket approval.</p>
        <div className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="console-session-id">Session id</label>
            <input id="console-session-id" className={styles.input} value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
          </div>
          <div className={styles.field}>
            <label htmlFor="console-trace-id">Trace id</label>
            <input id="console-trace-id" className={styles.input} value={traceId} onChange={(e) => setTraceId(e.target.value)} />
          </div>
          <div className={styles.field}>
            <label htmlFor="console-reference">Booking or case reference</label>
            <input id="console-reference" className={styles.input} value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          <div className={styles.field}>
            <label htmlFor="console-release">Release</label>
            <input id="console-release" className={styles.input} value={release} onChange={(e) => setRelease(e.target.value)} placeholder="1.4.2" />
          </div>
        </div>
        <fieldset className={styles.chips}>
          <legend>Role</legend>
          {ROLE_CHIPS.map((role) => (
            <Chip
              key={role}
              pressed={roles.includes(role)}
              onPressedChange={(next) => toggleRole(role, next)}
              dataEl={`CON-FIND-ROLE-${role.toUpperCase()}`}
            >
              {role.charAt(0).toUpperCase() + role.slice(1)}
            </Chip>
          ))}
        </fieldset>
        <Button variant="secondary" onClick={() => void search()} dataEl="CON-FIND-SEARCH-BTN">
          Search
        </Button>
        {searchError !== null && <p role="alert" className={styles.alert}>{searchError}</p>}
        {items !== null && (
          <table className={styles.table}>
            <caption className={styles.help}>Search results</caption>
            <thead>
              <tr>
                <th scope="col">Session</th>
                <th scope="col">Role</th>
                <th scope="col">Device</th>
                <th scope="col">Release</th>
                <th scope="col">Started</th>
                <th scope="col">Events</th>
                <th scope="col">Friction</th>
                <th scope="col">Errors</th>
                <th scope="col"><span className={styles.visuallyHidden}>Open</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.sessionId}>
                  <td>{item.sessionId}</td>
                  <td>{item.role}</td>
                  <td>{item.device}</td>
                  <td>{item.release}</td>
                  <td>{item.started}</td>
                  <td>{item.eventCount}</td>
                  <td>{item.frictionCount}</td>
                  <td>{item.errorCount}</td>
                  <td>
                    <Button
                      variant="neutral"
                      onClick={() => router.push(`/console/session/${encodeURIComponent(item.sessionId)}`)}
                    >
                      Open <span className={styles.visuallyHidden}>{item.sessionId}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
