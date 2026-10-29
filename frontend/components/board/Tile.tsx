import { StatusBadge } from '@/components/ui/StatusBadge';
import { ageLineText, categoryLabel } from '@/lib/board/format';
import type { BoardEntry, BoardStatus } from '@/lib/board/types';
import styles from './Tile.module.css';

// One service on the wall board (ui-screens.md, artboard "Main"). It shows only
// what the back end sent for this service, and it shows "?" and "Phone to
// confirm" rather than a number it cannot stand behind. The tile never shows a
// back-end id except the one data attribute the prompt asks for.

const VARIANT: Record<BoardStatus, string> = {
  accepting: styles.accepting,
  limited: styles.limited,
  'not-accepting': styles.notAccepting,
  'over-capacity': styles.overCapacity,
  'not-updated': styles.notUpdated,
  'out-of-hours': styles.outOfHours,
};

type Figure = {
  /** The big number, or null when there is none to show. */
  big: string | null;
  unit: string;
  /** The "Used N of M" line, or null for no bar. */
  bar: { label: string; percent: number } | null;
};

const UNKNOWN_UNIT = 'Phone to confirm';

function usedLabel(used: number | null, established: number): string {
  return `Used ${used === null ? '?' : used} of ${established}`;
}

/** Used over established as a percentage, kept between 0 and 100 and to one decimal place. */
function fillPercent(used: number | null, established: number): number {
  if (used === null) return 0;
  if (established <= 0) return used > 0 ? 100 : 0;
  return Math.round(Math.min(100, Math.max(0, (used / established) * 100)) * 10) / 10;
}

function figureFor(entry: BoardEntry): Figure {
  const { status, established, used } = entry;

  if (status === 'not-updated') {
    // Whatever the back end last held, the figure is not to be relied on.
    return { big: '?', unit: UNKNOWN_UNIT, bar: { label: usedLabel(null, established), percent: 100 } };
  }
  if (status === 'out-of-hours') {
    return { big: null, unit: 'Outside opening hours', bar: null };
  }

  const bar = { label: usedLabel(used, established), percent: fillPercent(used, established) };

  if (status === 'over-capacity') {
    const over = entry.overBy ?? (used !== null && used > established ? used - established : null);
    return over === null
      ? { big: '?', unit: UNKNOWN_UNIT, bar }
      : { big: `+${over}`, unit: entry.unitLabel, bar };
  }

  // Accepting, limited, not accepting. A service that reports occupancy has no
  // free count of its own, so it is worked out from the two figures the back end gave.
  const free = entry.effectiveAvailable ?? (used === null ? null : Math.max(0, established - used));
  return free === null
    ? { big: '?', unit: UNKNOWN_UNIT, bar }
    : { big: String(free), unit: entry.unitLabel, bar };
}

export function Tile({ entry, now }: { entry: BoardEntry; now: string | Date }) {
  const figure = figureFor(entry);
  const age = ageLineText(entry, now);
  const notUpdated = entry.status === 'not-updated';

  return (
    <article
      className={`${styles.tile} ${VARIANT[entry.status]}`}
      data-el="WALL-TILE"
      data-service-id={entry.serviceId}
      data-status={entry.status}
    >
      <div className={styles.top}>
        <div className={styles.who}>
          <h2 className={styles.name}>{entry.name}</h2>
          <p className={styles.category}>{categoryLabel(entry.category)}</p>
        </div>
        <StatusBadge status={entry.status} size="lg" />
      </div>

      <div className={styles.figure}>
        {figure.big === null ? null : <p className={styles.number} data-el="WALL-TILE-NUMBER">
            {figure.big}
          </p>}
        <div className={styles.words}>
          <p className={styles.unit}>{figure.unit}</p>
          {entry.comment ? (
            <p className={styles.comment} data-el="WALL-TILE-COMMENT">
              {entry.comment}
            </p>
          ) : null}
        </div>
      </div>

      {figure.bar === null ? null : (
        <div className={styles.usage}>
          <p className={styles.barLabel}>{figure.bar.label}</p>
          <div className={styles.bar} aria-hidden="true">
            <div className={styles.fill} data-bar-fill style={{ width: `${figure.bar.percent}%` }} />
          </div>
        </div>
      )}

      <p className={styles.age}>{notUpdated ? <strong>{age}</strong> : age}</p>
    </article>
  );
}
