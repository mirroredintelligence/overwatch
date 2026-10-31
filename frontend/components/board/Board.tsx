import { londonDate, londonTime } from '@/lib/board/format';
import type { Board as BoardData } from '@/lib/board/types';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import type { ScopeLinks } from '@/components/scope/ScopeSwitch';
import styles from './Board.module.css';
import { Legend } from './Legend';
import { LastKnownBanner, type LastKnown } from './LastKnownBanner';
import { PressureBanner } from './PressureBanner';
import { Tile } from './Tile';

// The call-centre wall board: a header, a grid of tiles in the order the back
// end sent them, the key and the footer line. It shows one organisation's board
// and only what it is given: the page reads that board with the paired screen's
// own session and never takes an organisation from the address.
//
// Every age is measured from the back end's clock (`generatedAt`), so the time
// in the header and the age under each tile always agree with each other and with
// the status the back end worked out.

const NO_SERVICES = 'No services are listed. Use the whiteboard and phone process.';

export function Board({
  board,
  lastKnown,
  streamPaused = false,
  subtitle = null,
  heading = null,
  ownSwitch,
}: {
  board: BoardData;
  /**
   * Set where a person (not a wall) reads the board: the header then offers the switch to the network board
   * when the viewer's organisation is in a network. A wall has no switch: its administrator sets its board.
   */
  ownSwitch?: ScopeLinks;
  /** The tenant's own heading (its organisation and its word for its system, TEN-069), or none. */
  heading?: string | null;
  /** The tenant's own line under the heading (its coordination team name, TEN-049), or none. */
  subtitle?: string | null;
  /** Set when the board must be shown as last known (W06). */
  lastKnown?: LastKnown;
  /** True when the live stream is down but the board is still being refreshed. */
  streamPaused?: boolean;
}) {
  // Current: every age is measured from the time the board was built. Last known:
  // from the time now, so the ages keep growing while the figures stand still.
  const now = lastKnown ? lastKnown.now : board.generatedAt;
  const title = heading ?? (board.organisation ? `${board.organisation} urgent care capacity` : 'Urgent care capacity');

  return (
    <main className={styles.board}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{title}</h1>
          {subtitle !== null ? <p className={styles.subtitle}>{subtitle}</p> : null}
        </div>
        <div className={styles.clock}>
          <time className={`${styles.time} tabular-nums`} dateTime={board.generatedAt}>
            {londonTime(board.generatedAt)}
          </time>
          <p className={styles.date}>{londonDate(board.generatedAt)}</p>
        </div>
      </header>

      {/* Which board this is, in words, on the screen itself: a wall has no address bar (TEN-069). It stays
          in every state, last known included. The network variant says the network's name instead (TEN-072). */}
      {ownSwitch === undefined ? <ScopeHeader scope="own" variant="wall" /> : <OwnScopeHeader {...ownSwitch} />}

      {lastKnown ? (
        <LastKnownBanner lastKnown={lastKnown} />
      ) : streamPaused ? (
        <p className={styles.note} data-el="WALL-STREAM-NOTE">
          Live updates paused. This board refreshes every minute.
        </p>
      ) : null}

      {/* Not while last known: a pressure claim from old figures must not look current. */}
      {lastKnown ? null : <PressureBanner board={board} />}

      {board.entries.length === 0 ? (
        <p className={styles.empty} role="status">
          {NO_SERVICES}
        </p>
      ) : (
        <ul className={styles.grid} aria-label="Services">
          {board.entries.map((entry) => (
            <li key={entry.serviceId} className={styles.cell}>
              <Tile entry={entry} now={now} lastKnown={lastKnown !== undefined} />
            </li>
          ))}
        </ul>
      )}

      <footer className={styles.footer}>
        <Legend />
        <p className={styles.privacy}>No patient information on this screen</p>
      </footer>
    </main>
  );
}
