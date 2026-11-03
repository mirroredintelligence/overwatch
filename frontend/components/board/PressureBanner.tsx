import { londonTime, reopensText } from '@/lib/board/format';
import type { Board } from '@/lib/board/types';
import styles from './PressureBanner.module.css';

// "System under pressure" (ui-screens.md, artboard "BoardSurge"; domain-rules 1.7).
// The back end decides when it shows: `allLimitedOrWorse` is true when every service
// that is in hours is limited, not accepting or over capacity, and out-of-hours
// services are left out. The count is the number of services in hours, so it agrees
// with the tiles a person can see. Words carry the meaning; the triangle and the tint
// only add to them. It is shown for a current board only (the board decides, see Board).
// It is a polite status, not an alert: it describes the board, it does not interrupt.

const TITLE = 'System under pressure';
const WORSE = 'limited, not accepting or over capacity.';
const PHONE = 'Phone to confirm before you offer a service.';

export function PressureBanner({ board }: { board: Pick<Board, 'allLimitedOrWorse' | 'entries'> }) {
  if (!board.allLimitedOrWorse) return null;
  const inHours = board.entries.filter((e) => e.status !== 'out-of-hours').length;
  // A flag with no service in hours behind it cannot be put in words ("All 0 services").
  if (inHours === 0) return null;
  const text = inHours === 1 ? `The only service in hours is ${WORSE}` : `All ${inHours} services are ${WORSE}`;
  return (
    <div className={`${styles.banner} ${styles.pressure}`} role="status" data-tone="warning" data-el="WALL-PRESSURE-BANNER">
      <span className={styles.pressureShape} aria-hidden="true" />
      <div>
        <p className={styles.title}>{TITLE}</p>
        <p className={styles.text}>
          <span>{text}</span> <span>{PHONE}</span>
        </p>
      </div>
    </div>
  );
}

// "Quiet overnight" (artboard "BoardQuiet"): most services are out of hours, so the few that take referrals
// are the board. Out-of-hours services are left out of every count, and this says so in words. It names the
// reopening time only when every out-of-hours service gives the same one. Words only from facts on the board:
// "overnight" only when the board's own clock says it is night.

const NIGHT_FROM = 22;
const NIGHT_TO = 7;

function isNight(generatedAt: string): boolean {
  const hour = Number(londonTime(generatedAt).slice(0, 2));
  return hour >= NIGHT_FROM || hour < NIGHT_TO;
}

function referralsText(inHours: number): string {
  if (inHours === 0) return 'None take referrals now.';
  return inHours === 1 ? '1 takes referrals now.' : `${inHours} take referrals now.`;
}

export function QuietBanner({ board }: { board: Pick<Board, 'entries' | 'generatedAt'> }) {
  const total = board.entries.length;
  const closed = board.entries.filter((e) => e.status === 'out-of-hours');
  // Quiet means most of the board is closed; half or fewer is a normal board with some services shut.
  if (closed.length * 2 <= total) return null;
  const reopening = new Set(closed.map((e) => (e.nextDueAt === null ? null : reopensText(e.nextDueAt, board.generatedAt))));
  const [only] = reopening;
  const until = reopening.size === 1 && only !== null && only !== undefined ? ` until ${only.replace(/^Reopens /, '')}` : '';
  const subject =
    closed.length === total
      ? total === 1
        ? 'The only service is'
        : `All ${total} services are`
      : `${closed.length} of ${total} services are`;
  return (
    <div className={`${styles.banner} ${styles.quiet}`} role="status" data-el="WALL-QUIET-BANNER">
      <svg className={styles.quietShape} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />
      </svg>
      <div>
        <p className={styles.title}>{isNight(board.generatedAt) ? 'Quiet overnight' : 'Quiet: most services are out of hours'}</p>
        <p className={styles.text}>{`${subject} out of hours${until}, so they are not counted. ${referralsText(total - closed.length)}`}</p>
      </div>
    </div>
  );
}
