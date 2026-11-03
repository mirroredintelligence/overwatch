'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { leadRead } from '@/lib/lead/browser';
import { dateTimeLine, overdueText } from '@/lib/lead/format';
import { screenListFrom, type ScreenList as List, type ScreenRow, type ScreenStatus } from '@/lib/screens/admin';
import { ScreenBoardChoice, type BoardOutcome } from './ScreenBoardChoice';
import { ScreenUnpair, type UnpairOutcome } from './ScreenUnpair';
import leadStyles from './Lead.module.css';
import styles from './ScreenList.module.css';

// The shift lead's wall screens page (docs/design/redesign/boards/lead/Screens.dc.html; docs/design/network-ui.md
// section 6, TEN-072; W9I): one card per organisation screen with a preview thumbnail, its place, its status in
// words and shape, when it was last seen and which board it shows. The actions are per state: change the board,
// pair again, unpair. Unpair asks on the screen's own card, in place. Ages are measured against the back end's
// clock (`asOf`), never the browser's. Nothing here holds a token, a hash or a pairing secret: the BFF does not
// send one. A failed read says so and never shows an empty list. The screens' ids and the networks' ids are in
// memory only, never in an address or an id.

const LIST_URL = '/api/bff/screens';
const REFRESH_MS = 60_000;
const SIGN_IN_AGAIN = '/sign-in?next=%2Flead%2Fscreens';
const PAIRING_PAGE = '/lead/screens/new';
const MINUTE_MS = 60_000;

type Load = { kind: 'loading' } | { kind: 'ready'; list: List } | { kind: 'failed' };
type Notice = { tone: 'done' | 'problem' | 'ended'; text: string } | null;
type Asking = { kind: 'unpair' | 'board'; row: ScreenRow } | null;

// The status in words, as the board says them, and the shape that goes with each (StatusTag: the shape is
// decoration, the word carries the meaning).
const WORDS: Record<ScreenStatus, string> = {
  online: 'Online',
  offline: 'Not showing the board',
  waiting: 'Waiting for a code',
  'never-connected': 'Never connected',
  revoked: 'Unpaired',
};

const TAGS: Record<ScreenStatus, StatusTagVariant> = {
  online: 'live',
  offline: 'closed',
  waiting: 'waiting',
  'never-connected': 'todo',
  revoked: 'paused',
};

// The board's eight blank tiles on a live screen's thumbnail. The list carries no board counts, so the tiles are
// not drawn from them (see the report): they only say that a live board is there.
const TILES = [0, 1, 2, 3, 4, 5, 6, 7];

/** "just now", "2 min ago", "2 hrs 20 min ago", against the back end's clock. */
function ago(iso: string, asOf: string): string {
  const minutes = Math.floor((Date.parse(asOf) - Date.parse(iso)) / MINUTE_MS);
  return minutes < 1 ? 'just now' : `${overdueText(minutes)} ago`;
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

/** The facts line under the status, in the board's words: "Shows X · seen just now", "Last seen 2 hrs ago. Shows X." */
function Facts({ row, asOf }: { row: ScreenRow; asOf: string }) {
  const shows = showsText(row).main;
  if (row.state === 'revoked') return <p className={styles.facts}>Unpaired on {when(row.revokedAt)}.</p>;
  const seen = row.lastSeenAt === null ? null : ago(row.lastSeenAt, asOf);
  if (row.state === 'offline') {
    return (
      <p className={styles.facts}>
        {seen === null ? 'Not seen yet' : <>Last seen <time dateTime={row.lastSeenAt ?? undefined}>{seen}</time></>}
        {`. Shows ${shows}.`}
      </p>
    );
  }
  return (
    <p className={styles.facts}>
      {`Shows ${shows} · `}
      {seen === null ? 'not seen yet' : <>seen <time dateTime={row.lastSeenAt ?? undefined}>{seen}</time></>}
    </p>
  );
}

function ScreenCard({
  row,
  asOf,
  onBoard,
  onUnpair,
  unpairRef,
}: {
  row: ScreenRow;
  asOf: string;
  onBoard: () => void;
  onUnpair: () => void;
  unpairRef: (element: HTMLButtonElement | null) => void;
}) {
  const live = row.state !== 'revoked';
  const note = showsText(row).note;
  return (
    <section aria-label={row.name} className={row.state === 'offline' ? `${styles.card} ${styles.cardAlert}` : styles.card}>
      <div className={row.state === 'online' ? styles.thumb : `${styles.thumb} ${styles.thumbIdle}`} aria-hidden="true" data-el="SCREENS-THUMB">
        {row.state === 'online' ? TILES.map((tile) => <span key={tile} className={styles.tile} />) : null}
      </div>
      <div className={styles.head}>
        <div className={styles.titles}>
          <h2 className={styles.name}>{row.name}</h2>
          <p className={styles.place}>{row.location ?? 'Not given'}</p>
        </div>
        <StatusTag variant={TAGS[row.state]}>{WORDS[row.state]}</StatusTag>
      </div>
      <Facts row={row} asOf={asOf} />
      {note === null ? null : <p className={styles.note}>{note}</p>}
      <div className={styles.actions}>
        {live ? (
          <Button variant="secondary" onClick={onBoard} ariaLabel={`Change the board for ${row.name}`} dataEl="SCREENS-BOARD-BTN">
            Change the board
          </Button>
        ) : null}
        {CAN_REPAIR.includes(row.state) ? (
          <Button variant="secondary" href={PAIRING_PAGE} ariaLabel={`Pair again for ${row.name}`} dataEl="SCREENS-REPAIR-BTN">
            Pair again
          </Button>
        ) : null}
        {live ? (
          <button type="button" ref={unpairRef} className={styles.textAction} onClick={onUnpair} aria-label={`Unpair ${row.name}`} data-el="SCREENS-UNPAIR-BTN">
            Unpair
          </button>
        ) : null}
      </div>
    </section>
  );
}

export function ScreenList() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [asking, setAsking] = useState<Asking>(null);
  const [notice, setNotice] = useState<Notice>(null);
  // The Unpair buttons by screen, so a question that closed without a result gives the focus back to its card.
  const unpairButtons = useRef(new Map<string, HTMLButtonElement>());
  const returnFocusTo = useRef<string | null>(null);

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

  useEffect(() => {
    if (asking !== null || returnFocusTo.current === null) return;
    unpairButtons.current.get(returnFocusTo.current)?.focus();
    returnFocusTo.current = null;
  }, [asking]);

  const list = load.kind === 'ready' ? load.list : null;

  function closeUnpair(row: ScreenRow) {
    returnFocusTo.current = row.deviceId;
    setAsking(null);
  }

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

  function rememberUnpair(deviceId: string, element: HTMLButtonElement | null) {
    if (element === null) unpairButtons.current.delete(deviceId);
    else unpairButtons.current.set(deviceId, element);
  }

  return (
    <main className={styles.page}>
      <PageHeader
        title="Wall screens"
        actions={
          <Button variant="primary" href={PAIRING_PAGE} dataEl="SCREENS-ADD-BTN">
            Add a wall screen
          </Button>
        }
      >
        <p className={styles.intro}>The screens that show a live board. A screen shows capacity only, never patient information.</p>
      </PageHeader>

      {notice !== null && notice.tone === 'done' ? (
        <p role="status" className={leadStyles.notice}>
          {notice.text}
        </p>
      ) : null}
      {notice !== null && notice.tone !== 'done' ? (
        <p role="alert" className={leadStyles.fieldError}>
          {notice.text}
          {notice.tone === 'ended' ? (
            <a className={leadStyles.signInLink} href={SIGN_IN_AGAIN}>
              Sign in
            </a>
          ) : null}
        </p>
      ) : null}

      {load.kind === 'failed' ? (
        <p role="alert" className={leadStyles.fieldError}>
          We could not load the screens.
        </p>
      ) : null}
      {load.kind === 'loading' ? <p className={leadStyles.muted}>Loading the screens.</p> : null}

      {list !== null && list.screens.length === 0 ? <p>No screens are connected yet.</p> : null}

      {list !== null && list.screens.length > 0 ? (
        <ul className={styles.grid} aria-label="Wall screens in your organisation">
          {list.screens.map((row) => (
            <li key={row.deviceId} className={styles.cell}>
              {asking?.kind === 'unpair' && asking.row.deviceId === row.deviceId ? (
                <ScreenUnpair
                  row={row}
                  status={<StatusTag variant={TAGS[row.state]}>{WORDS[row.state]}</StatusTag>}
                  onClose={() => closeUnpair(row)}
                  onResult={(result) => unpaired(row, result)}
                />
              ) : (
                <ScreenCard
                  row={row}
                  asOf={list.asOf}
                  onBoard={() => setAsking({ kind: 'board', row })}
                  onUnpair={() => setAsking({ kind: 'unpair', row })}
                  unpairRef={(element) => rememberUnpair(row.deviceId, element)}
                />
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {asking?.kind === 'board' && list !== null ? (
        <ScreenBoardChoice row={asking.row} networks={list.networks} onClose={() => setAsking(null)} onResult={(outcome) => boardChosen(asking.row, outcome)} />
      ) : null}
    </main>
  );
}
