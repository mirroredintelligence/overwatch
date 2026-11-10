import type { ReactNode } from 'react';
import { londonDate, londonTime } from '@/lib/board/format';
import type { Board as BoardData } from '@/lib/board/types';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { ScopeNotice } from '@/components/scope/ScopeNotice';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import type { WallScope } from '@/lib/board/scope';
import type { ScopeLinks } from '@/components/scope/ScopeSwitch';
import styles from './Board.module.css';
import { Legend } from './Legend';
import { LastKnownBanner, type LastKnown } from './LastKnownBanner';
import { PressureBanner, QuietBanner } from './PressureBanner';
import { Tile } from './Tile';

// The call-centre wall board: a header, a grid of tiles in the order the back
// end sent them, the key and the footer line. It shows one organisation's board
// and only what it is given: the page reads that board with the paired screen's
// own session and never takes an organisation from the address.
//
// Every age is measured from the back end's clock (`generatedAt`), so the time
// in the header and the age under each tile always agree with each other and with
// the status the back end worked out.
//
// One renderer, two views. The wall view is the paired screen's own; the advisor view is the same board
// read by a person inside the staff frame (artboards BoardNormal, BoardSurge, BoardQuiet, BoardDown): it is
// headed "Board right now" and carries the page's one primary action, which the page gives (`action`).

const NO_SERVICES = 'No services are listed. Use the whiteboard and phone process.';
const LOADING_WIDTHS = [62, 48, 70, 56, 80, 66, 52, 74, 44];

/** The advisor board while it is being read (artboard BoardLoading): the shape of nine tiles, and no figure. */
export function BoardLoading() {
  return (
    <main className={`${styles.board} ${styles.advisor}`} aria-busy="true">
      <header className={styles.heading}>
        <div className={styles.headingText}>
          <h1 className={styles.title}>Board right now</h1>
        </div>
      </header>
      <Loading label="Loading the board.">
        <div className={styles.grid}>
          {LOADING_WIDTHS.map((width, index) => (
            <div key={index} className={styles.loadingTile} data-el="BOARD-LOADING-TILE">
              <div className={styles.loadingTop}>
                <div className={styles.loadingNames}>
                  <Skeleton shape="title" width={`${width}%`} />
                  <Skeleton shape="line" width="46%" />
                </div>
                <Skeleton shape="chip" />
              </div>
              <Skeleton shape="title" width="38%" />
              <Skeleton shape="line" width="100%" />
              <Skeleton shape="line" width="62%" />
            </div>
          ))}
        </div>
      </Loading>
      <p className={styles.note}>This takes a moment.</p>
    </main>
  );
}

export function Board({
  board,
  lastKnown,
  streamPaused = false,
  subtitle = null,
  heading = null,
  ownSwitch,
  scope,
  fellBackFrom = null,
  view = 'wall',
  action,
}: {
  board: BoardData;
  /**
   * Which board the wall shows (TEN-072). A network says its name in the header and as the heading and has
   * no sorting footer; a screen that fell back says so in a warning and shows its own board. Absent: its own.
   */
  scope?: WallScope;
  /** The name of the network a screen that fell back was showing, when it is known; none otherwise. */
  fellBackFrom?: string | null;
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
  /** 'wall' (the default) is the paired screen; 'advisor' is a person reading it inside the staff frame. */
  view?: 'wall' | 'advisor';
  /** The advisor view's one primary action (Start a new call). Not drawn while the board is last known. */
  action?: ReactNode;
}) {
  // Current: every age is measured from the time the board was built. Last known:
  // from the time now, so the ages keep growing while the figures stand still.
  const now = lastKnown ? lastKnown.now : board.generatedAt;
  const network = scope !== undefined && scope.boardScope === 'network' ? scope.networkName : null;
  const advisor = view === 'advisor';
  const wallTitle = network !== null ? `${network} capacity` : (heading ?? (board.organisation ? `${board.organisation} urgent care capacity` : 'Urgent care capacity'));
  const advisorTitle = network !== null ? wallTitle : lastKnown ? 'Board: last known' : 'Board right now';

  return (
    <main className={advisor ? `${styles.board} ${styles.advisor}` : styles.board}>
      {advisor ? (
        <header className={styles.heading}>
          <div className={styles.headingText}>
            <h1 className={styles.title}>{advisorTitle}</h1>
            <p className={styles.subline} data-el="BOARD-SUBLINE">
              {lastKnown ? (
                <>
                  <time className="tabular-nums" dateTime={lastKnown.now}>
                    {londonTime(lastKnown.now)}
                  </time>
                  {` on this screen · figures are from before ${londonTime(lastKnown.since)}`}
                </>
              ) : (
                <>
                  <time className="tabular-nums" dateTime={board.generatedAt}>
                    {londonTime(board.generatedAt)}
                  </time>
                  {` · ${londonDate(board.generatedAt)} · the same board as the wall`}
                </>
              )}
            </p>
          </div>
          {action && !lastKnown ? <div className={styles.action}>{action}</div> : null}
        </header>
      ) : (
        <header className={styles.header}>
          <div>
            <h1 className={styles.title}>{wallTitle}</h1>
            {subtitle !== null ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </div>
          <div className={styles.clock}>
            <time className={`${styles.time} tabular-nums`} dateTime={board.generatedAt}>
              {londonTime(board.generatedAt)}
            </time>
            <p className={styles.date}>{londonDate(board.generatedAt)}</p>
          </div>
        </header>
      )}

      {/* Which board this is, in words, on the screen itself: a wall has no address bar (TEN-069). It stays
          in every state, last known included. The network variant says the network's name instead (TEN-072). */}
      {network !== null ? (
        <ScopeHeader scope="network" networkName={network} variant="wall" />
      ) : ownSwitch === undefined ? (
        <ScopeHeader scope="own" variant="wall" />
      ) : (
        <OwnScopeHeader {...ownSwitch} />
      )}

      {/* The screen was set to a network it may no longer read: it says so and shows its own board; it
          never goes blank and never falls back silently (docs/design/network-ui.md section 5). It stays
          until the administrator changes the screen's board, in every state. */}
      {scope?.fallback === true ? (
        <ScopeNotice
          tone="warning"
          title={`No longer showing ${fellBackFrom ?? 'the network board'}. Showing: Our organisation.`}
        />
      ) : null}

      {lastKnown ? (
        <LastKnownBanner lastKnown={lastKnown} />
      ) : streamPaused ? (
        <p className={styles.note} data-el="WALL-STREAM-NOTE">
          Live updates paused. This board refreshes every minute.
        </p>
      ) : null}

      {/* Not while last known: a claim from old figures (pressure, quiet) must not look current. */}
      {lastKnown ? null : <PressureBanner board={board} />}
      {lastKnown ? null : <QuietBanner board={board} />}

      {board.entries.length === 0 ? (
        <p className={styles.empty} role="status">
          {NO_SERVICES}
        </p>
      ) : (
        <ul className={styles.grid} aria-label="Services">
          {board.entries.map((entry) => (
            <li key={entry.serviceId} className={styles.cell}>
              <Tile entry={entry} now={now} lastKnown={lastKnown !== undefined} attention={advisor} />
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
