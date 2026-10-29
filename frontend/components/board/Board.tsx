import { londonDate, londonTime } from '@/lib/board/format';
import type { Board as BoardData } from '@/lib/board/types';
import styles from './Board.module.css';
import { Legend } from './Legend';
import type { LastKnown } from './LastKnownBanner';
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
}: {
  board: BoardData;
  /** Set when the board must be shown as last known (W06). */
  lastKnown?: LastKnown;
  /** True when the live stream is down but the board is still being refreshed. */
  streamPaused?: boolean;
}) {
  const now = board.generatedAt;
  const title = board.organisation
    ? `${board.organisation} urgent care capacity`
    : 'Urgent care capacity';

  return (
    <main className={styles.board}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{title}</h1>
          <p className={styles.subtitle}>Single point of access</p>
        </div>
        <div className={styles.clock}>
          <time className={`${styles.time} tabular-nums`} dateTime={now}>
            {londonTime(now)}
          </time>
          <p className={styles.date}>{londonDate(now)}</p>
        </div>
      </header>

      {board.entries.length === 0 ? (
        <p className={styles.empty} role="status">
          {NO_SERVICES}
        </p>
      ) : (
        <ul className={styles.grid} aria-label="Services">
          {board.entries.map((entry) => (
            <li key={entry.serviceId} className={styles.cell}>
              <Tile entry={entry} now={now} />
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
