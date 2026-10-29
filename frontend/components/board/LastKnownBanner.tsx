import { ShapeIcon } from '@/components/ui/StatusBadge';
import { dataAgeText, londonTime } from '@/lib/board/format';
import type { Assessment } from '@/lib/board/liveness';
import styles from './LastKnownBanner.module.css';

export type LastKnown = Extract<Assessment, { mode: 'last-known' }>;

// Shown above the tiles when the board cannot be refreshed or is too old
// (ui-screens.md, artboard "BoardDown"). The alert holds only words that do not
// change while the board stays last known, so a screen reader announces it once.
// The line that counts up (how long ago the board was built) is outside the alert.
export function LastKnownBanner({ lastKnown }: { lastKnown: LastKnown }) {
  return (
    <div className={styles.wrap}>
      <div role="alert" className={styles.banner} data-el="WALL-OFFLINE-BANNER">
        <div className={styles.head}>
          <span className={styles.icon}>
            <ShapeIcon shape="dashed-circle" />
          </span>
          <p className={styles.title}>{`Tool offline since ${londonTime(lastKnown.since)}`}</p>
        </div>
        <p className={styles.body}>
          Figures are the last known and may be wrong. Use the whiteboard and phone process.
        </p>
      </div>
      <p className={styles.refreshed} data-el="WALL-LAST-REFRESH">
        {`Board last refreshed ${londonTime(lastKnown.asOf)} · ${dataAgeText(lastKnown.asOf, lastKnown.now)}`}
      </p>
    </div>
  );
}
