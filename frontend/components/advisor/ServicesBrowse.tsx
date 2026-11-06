'use client';

import { useEffect, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import { fetchBoardFromBff } from '@/lib/board/client';
import { categoryLabel } from '@/lib/board/format';
import type { Board } from '@/lib/board/types';
import { BROWSE_STATUSES, browseRows, countsOf } from '@/lib/advisor/servicesBrowse';
import styles from './ServicesBrowse.module.css';

// The services of the organisation by state (DEC-1343), opened from the counts on the advisor home. Each state is a
// toggle with its count; none chosen shows all five. The list is by name, not by status, and a late or old figure
// reads "Current capacity unavailable", never a number.

type State = { kind: 'loading' } | { kind: 'ready'; board: Board; now: number } | { kind: 'failed' };

export function ServicesBrowse({ initial }: { initial: StatusCode[] }) {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [selected, setSelected] = useState<StatusCode[]>(initial);

  useEffect(() => {
    const controller = new AbortController();
    fetchBoardFromBff(controller.signal)
      .then(({ board, serverTime }) => setState({ kind: 'ready', board, now: serverTime ?? Date.now() }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'failed' });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === 'loading') {
    return (
      <Loading label="Loading the services.">
        <Skeleton shape="block" />
      </Loading>
    );
  }
  if (state.kind === 'failed') {
    return <p className={styles.failed}>The services could not be read. Open the wall board view to try again.</p>;
  }

  const counts = countsOf(state.board.entries);
  const rows = browseRows(state.board.entries, selected, state.now);
  const toggle = (status: StatusCode) =>
    setSelected((current) => (current.includes(status) ? current.filter((item) => item !== status) : [...current, status]));

  return (
    <div className={styles.page}>
      <div role="group" aria-label="Show services by state" className={styles.filters}>
        {BROWSE_STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            className={styles.chip}
            aria-pressed={selected.includes(status)}
            onClick={() => toggle(status)}
            data-el={`ADV-SERVICES-FILTER-${status.toUpperCase()}`}
          >
            <span className={styles.shape}>
              <ShapeIcon shape={STATUS_SHAPES[status]} />
            </span>
            {`${STATUS_LABELS[status]} (${counts[status]})`}
          </button>
        ))}
      </div>
      <p className={styles.note} role="status">{`${rows.length} ${rows.length === 1 ? 'service' : 'services'}. Listed by name, not ranked.`}</p>
      {rows.length === 0 ? (
        <p className={styles.none}>No service is in this state.</p>
      ) : (
        <ul className={styles.rows} data-el="ADV-SERVICES-LIST">
          {rows.map((row) => (
            <li key={row.serviceId} className={styles.row}>
              <div className={styles.text}>
                <h2 className={styles.name}>{row.name}</h2>
                <p className={styles.caption}>{`${categoryLabel(row.category)} · ${row.updated}`}</p>
                <StatusBadge status={row.status} />
              </div>
              <div className={styles.figure}>
                {row.figure === null ? (
                  <p className={styles.unavailable}>Current capacity unavailable</p>
                ) : (
                  <>
                    <p className={styles.number}>{row.figure}</p>
                    <p className={styles.unit}>{row.unitLabel}</p>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
