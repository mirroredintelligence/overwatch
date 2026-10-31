'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { leadRead } from '@/lib/lead/browser';
import { dateTimeLine, overdueText } from '@/lib/lead/format';
import { londonTime } from '@/lib/board/format';
import { screenListFrom, STATUS_WORDS, type ScreenList as List, type ScreenRow, type ScreenStatus } from '@/lib/screens/admin';
import { ScreenBoardChoice, type BoardOutcome } from './ScreenBoardChoice';
import { ScreenUnpair, type UnpairOutcome } from './ScreenUnpair';
import styles from './Lead.module.css';

// The shift lead's wall screens page (docs/design/network-ui.md section 6, TEN-072; W9I): the
// organisation's screens with their place, status in words (and a shape), when each was last seen and
// which board it shows, and the three things a lead does to one: change its board, unpair it, pair it
// again. Ages are measured against the back end's clock (`asOf`), never the browser's. Nothing here holds
// a token, a hash or a pairing secret: the BFF does not send one. A failed read says so and never shows an
// empty table. The screens' ids and the networks' ids are in memory only, never in an address or an id.

const LIST_URL = '/api/bff/screens';
const REFRESH_MS = 60_000;
const SIGN_IN_AGAIN = '/sign-in?next=%2Flead%2Fscreens';
const PAIRING_PAGE = '/lead/screens/new';
const MINUTE_MS = 60_000;

type Load = { kind: 'loading' } | { kind: 'ready'; list: List } | { kind: 'failed' };
type Notice = { tone: 'done' | 'problem' | 'ended'; text: string } | null;
type Asking = { kind: 'unpair' | 'board'; row: ScreenRow } | null;

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

/** The status in words: "Online, updated 09:59", "Offline since Fri 30 Oct, 07:40", "Waiting to be connected". */
function statusText(row: ScreenRow): string {
  const word = STATUS_WORDS[row.state];
  if (row.state === 'online' && row.lastSeenAt !== null) return `${word}, updated ${londonTime(row.lastSeenAt)}`;
  if (row.state === 'offline' && row.lastSeenAt !== null) return `${word} since ${dateTimeLine(Date.parse(row.lastSeenAt))}`;
  return word;
}

const when = (iso: string | null): string => (iso === null ? 'Not recorded' : dateTimeLine(Date.parse(iso)));

/** What the screen shows, in the design's words; a network that is no longer open to it is said. */
function showsText(row: ScreenRow): { main: string; note: string | null } {
  if (row.boardScope === 'network' && row.networkAvailable) return { main: `Network, ${row.networkName ?? 'network'}`, note: null };
  if (row.boardScope === 'network') return { main: 'Our organisation', note: `Set to Network, ${row.networkName ?? 'a network'}, which is no longer open to it.` };
  return { main: 'Our organisation', note: null };
}

// Pairing again is for a screen that is not showing the board and is not waiting for its code.
const CAN_REPAIR: readonly ScreenStatus[] = ['offline', 'never-connected', 'revoked'];

export function ScreenList() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [asking, setAsking] = useState<Asking>(null);
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

  function unpaired(row: ScreenRow, result: UnpairOutcome) {
    setAsking(null);
    if (result === 'done') setNotice({ tone: 'done', text: `${row.name} was unpaired.` });
    else if (result === 'gone') setNotice({ tone: 'problem', text: 'That screen is not in the list any more.' });
    else setNotice({ tone: 'ended', text: 'Your session has ended.' });
    void reload();
  }

  function boardChosen(row: ScreenRow, outcome: BoardOutcome) {
    setAsking(null);
    if (outcome.kind === 'saved') setNotice({ tone: 'done', text: `${row.name} now shows ${outcome.choice}.` });
    else if (outcome.kind === 'stale') setNotice({ tone: 'problem', text: 'Someone else changed this screen’s board. The list has been read again. Choose again.' });
    else if (outcome.kind === 'gone') setNotice({ tone: 'problem', text: 'That screen or that board is not available any more. The list has been read again.' });
    else setNotice({ tone: 'ended', text: 'Your session has ended.' });
    void reload();
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Wall screens</h1>
      <p className={styles.muted}>The screens that show a live board. A screen shows capacity only, never patient information.</p>

      <div className={styles.actions}>
        <Button variant="primary" href={PAIRING_PAGE} dataEl="SCREENS-ADD-BTN">
          Add a wall screen
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
          <table className={styles.table} data-el="SCREENS-LIST-TABLE">
            <caption className={styles.caption}>Wall screens in your organisation</caption>
            <thead>
              <tr>
                <th scope="col">Screen</th>
                <th scope="col">Where it is</th>
                <th scope="col">Status</th>
                <th scope="col">Last seen</th>
                <th scope="col">Shows</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.screens.map((row) => {
                const shows = showsText(row);
                const live = row.state !== 'revoked';
                return (
                  <tr key={row.deviceId}>
                    <td>
                      <span className={styles.screenName}>{row.name}</span>
                    </td>
                    <td>{row.location ?? 'Not given'}</td>
                    <td>
                      <span className={styles.screenStatus}>
                        <Shape status={row.state} />
                        {statusText(row)}
                      </span>
                    </td>
                    <td>{row.state === 'revoked' ? when(row.revokedAt) : seenText(row, list.asOf)}</td>
                    <td>
                      {shows.main}
                      {shows.note === null ? null : <span className={styles.screenNote}>{shows.note}</span>}
                    </td>
                    <td>
                      <div className={styles.rowActions}>
                        {live ? (
                          <Button variant="secondary" onClick={() => setAsking({ kind: 'board', row })} ariaLabel={`Change board for ${row.name}`} dataEl="SCREENS-BOARD-BTN">
                            Change board
                          </Button>
                        ) : null}
                        {live ? (
                          <Button variant="secondary" onClick={() => setAsking({ kind: 'unpair', row })} ariaLabel={`Unpair ${row.name}`} dataEl="SCREENS-UNPAIR-BTN">
                            Unpair
                          </Button>
                        ) : null}
                        {CAN_REPAIR.includes(row.state) ? (
                          <Button variant="secondary" href={PAIRING_PAGE} ariaLabel={`Re-pair ${row.name}`} dataEl="SCREENS-REPAIR-BTN">
                            Re-pair
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {asking?.kind === 'unpair' ? <ScreenUnpair row={asking.row} onClose={() => setAsking(null)} onResult={(result) => unpaired(asking.row, result)} /> : null}
      {asking?.kind === 'board' && list !== null ? (
        <ScreenBoardChoice row={asking.row} networks={list.networks} onClose={() => setAsking(null)} onResult={(outcome) => boardChosen(asking.row, outcome)} />
      ) : null}
    </main>
  );
}
