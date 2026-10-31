'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { leadPost, newIdempotencyKey, leadRead } from '@/lib/lead/browser';
import { dateTimeLine, overdueText } from '@/lib/lead/format';
import { screenListFrom, STATUS_WORDS, type ScreenList as List, type ScreenRow, type ScreenStatus } from '@/lib/screens/admin';
import dialogStyles from '@/components/advisor/dialog-body.module.css';
import styles from './Lead.module.css';

// The shift lead's list of the organisation's wall screens and the way to disconnect one (W9I, TEN-072).
// A screen is listed by the name and place the lead gave it, with its status in words (and a shape),
// when it was paired and when it was last seen. Ages are measured against the back end's clock (`asOf`),
// never the browser's. Disconnecting asks first, names the screen, and ends it at once at the back end:
// the screen then shows "This screen was disconnected" and goes back to its pairing page. Nothing here
// holds a token, a hash or a pairing secret: the BFF does not send one. A failed read says so and never
// shows an empty table.

const LIST_URL = '/api/bff/screens';
const REFRESH_MS = 60_000;
const SIGN_IN_AGAIN = '/sign-in?next=%2Flead%2Fscreens';
const MINUTE_MS = 60_000;

type Load = { kind: 'loading' } | { kind: 'ready'; list: List } | { kind: 'failed' };
type Notice = { tone: 'done' | 'gone' | 'ended'; text: string } | null;

const SHAPES: Record<ScreenStatus, string> = {
  online: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16Z',
  offline: 'M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z',
  waiting: 'M12 4v16M4 12h16',
  'never-connected': 'M6 6l12 12M18 6 6 18',
  revoked: 'M5 12h14',
};

function Shape({ status }: { status: ScreenStatus }) {
  const filled = status === 'online';
  return (
    <svg className={styles.screenShape} viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={2} strokeLinecap="round">
      <path d={SHAPES[status]} />
    </svg>
  );
}

function seenText(row: ScreenRow, asOf: string): string {
  if (row.lastSeenAt === null) return 'Not seen yet';
  const minutes = Math.floor((Date.parse(asOf) - Date.parse(row.lastSeenAt)) / MINUTE_MS);
  return minutes < 1 ? 'Just now' : `${overdueText(minutes)} ago`;
}

const when = (iso: string | null): string => (iso === null ? 'Not recorded' : dateTimeLine(Date.parse(iso)));

export function ScreenList() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [asking, setAsking] = useState<ScreenRow | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const reload = useCallback(async () => {
    const result = await leadRead(LIST_URL);
    try {
      if (!result.ok) throw new Error('refused');
      setLoad({ kind: 'ready', list: screenListFrom(result.body) });
    } catch {
      // A list already on screen stays; one that never loaded says so.
      setLoad((current) => (current.kind === 'ready' ? current : { kind: 'failed' }));
    }
  }, []);

  useEffect(() => {
    let live = true;
    const run = () => {
      if (live) void reload();
    };
    run();
    const timer = setInterval(run, REFRESH_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [reload]);

  const list = load.kind === 'ready' ? load.list : null;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Wall screens</h1>
      <p className={styles.muted}>The screens that show your organisation’s live board. A screen shows capacity only, never patient information.</p>

      <div className={styles.actions}>
        <Button variant="primary" href="/lead/screens/new" dataEl="LEAD-SCREENS-ADD-BTN">
          Add a screen
        </Button>
        <Button variant="neutral" href="/lead" dataEl="LEAD-SCREENS-BACK-BTN">
          Back to the shift lead page
        </Button>
      </div>

      {notice !== null && notice.tone === 'done' ? (
        <p role="status" className={styles.notice}>
          {notice.text}
        </p>
      ) : null}
      {notice !== null && notice.tone !== 'done' ? (
        <p role="alert" className={styles.fieldError}>
          {notice.text}
          {notice.tone === 'ended' ? (
            <a className={styles.signInLink} href={SIGN_IN_AGAIN}>
              Sign in
            </a>
          ) : null}
        </p>
      ) : null}

      {load.kind === 'failed' ? (
        <p role="alert" className={styles.fieldError}>
          We could not load the screens.
        </p>
      ) : null}
      {load.kind === 'loading' ? <p className={styles.muted}>Loading the screens.</p> : null}

      {list !== null && list.screens.length === 0 ? <p>No screens are connected yet.</p> : null}

      {list !== null && list.screens.length > 0 ? (
        <div className={styles.scrollBox}>
          <table className={styles.table}>
            <caption className={styles.caption}>Wall screens in your organisation</caption>
            <thead>
              <tr>
                <th scope="col">Screen</th>
                <th scope="col">Status</th>
                <th scope="col">Paired</th>
                <th scope="col">Last seen</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {list.screens.map((row) => (
                <tr key={row.deviceId}>
                  <td>
                    <span className={styles.screenName}>{row.name}</span>
                    {row.location === null ? null : <span className={styles.screenPlace}>{row.location}</span>}
                  </td>
                  <td>
                    <span className={styles.screenStatus}>
                      <Shape status={row.state} />
                      {STATUS_WORDS[row.state]}
                    </span>
                  </td>
                  <td>{when(row.pairedAt)}</td>
                  <td>{row.state === 'revoked' ? when(row.revokedAt) : seenText(row, list.asOf)}</td>
                  <td>
                    {row.state === 'revoked' ? null : (
                      <Button variant="secondary" onClick={() => setAsking(row)} dataEl={`LEAD-SCREEN-DISCONNECT-${row.deviceId}`}>
                        Disconnect<span className={styles.srOnly}> {row.name}</span>
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {asking === null ? null : (
        <DisconnectDialog
          row={asking}
          onClose={() => setAsking(null)}
          onResult={(result) => {
            setAsking(null);
            if (result === 'done') setNotice({ tone: 'done', text: `${asking.name} was disconnected.` });
            else if (result === 'gone') setNotice({ tone: 'gone', text: 'That screen is not in the list any more.' });
            else setNotice({ tone: 'ended', text: 'Your session has ended.' });
            void reload();
          }}
        />
      )}
    </main>
  );
}

type Outcome = 'done' | 'gone' | 'ended';

// The key and the busy flag live in the dialog, so a new dialog for another screen starts with a new key
// and a second try of the same one sends the same key (the back end then answers it as one revoke).
function DisconnectDialog({ row, onClose, onResult }: { row: ScreenRow; onClose: () => void; onResult: (result: Outcome) => void }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = useRef<string>(newIdempotencyKey());
  const sending = useRef(false);

  async function disconnect() {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setFailed(false);
    const result = await leadPost(`/api/bff/screens/${encodeURIComponent(row.deviceId)}/revoke`, undefined, key.current);
    sending.current = false;
    setBusy(false);
    if (result.ok) onResult('done');
    else if (result.status === 404) onResult('gone');
    else if (result.status === 401 || result.status === 403) onResult('ended');
    else setFailed(true);
  }

  return (
    <Dialog title={`Disconnect ${row.name}?`} dataEl="LEAD-SCREEN-DISCONNECT-DIALOG" onClose={onClose}>
      <p className={dialogStyles.text}>
        This screen will stop showing the board straight away and go back to its pairing page. To use it again, pair it again with a new code.
      </p>
      {failed ? (
        <p role="alert" className={dialogStyles.error}>
          The screen could not be disconnected. Try again.
        </p>
      ) : null}
      <div className={dialogStyles.actions}>
        <Button variant="neutral" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" busy={busy} onClick={() => void disconnect()} dataEl="LEAD-SCREEN-DISCONNECT-CONFIRM">
          Disconnect screen
        </Button>
      </div>
    </Dialog>
  );
}
