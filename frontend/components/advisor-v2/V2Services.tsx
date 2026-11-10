'use client';

import { useEffect, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import { readOverview } from '@/lib/advisor/v2/browser';
import { capacityToOption, COUNTED_STATUSES, type CountedStatus, type Overview } from '@/lib/advisor/v2/overview';
import { ServiceRows } from './ServiceRows';
import styles from './V2.module.css';

// The services of one state or more (DEC-1366), opened from a count on Capacity. By name, never by status; a late or
// old figure reads "Current capacity unavailable". Each row links to the service's page.

type State = { kind: 'loading' } | { kind: 'ready'; overview: Overview; now: number } | { kind: 'failed' };

export function V2Services({ initial }: { initial: CountedStatus[] }) {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [selected, setSelected] = useState<CountedStatus[]>(initial);

  useEffect(() => {
    let live = true;
    readOverview().then((overview) => {
      if (live) setState(overview === null ? { kind: 'failed' } : { kind: 'ready', overview, now: Date.now() });
    });
    return () => {
      live = false;
    };
  }, []);

  if (state.kind === 'loading') {
    return (
      <Loading label="Loading the services.">
        <Skeleton shape="block" />
      </Loading>
    );
  }
  if (state.kind === 'failed') {
    return (
      <p className={styles.failed} role="alert">
        The services could not be read. Try again.
      </p>
    );
  }

  const wanted = new Set<string>(selected.length === 0 ? COUNTED_STATUSES : selected);
  const rows = state.overview.services.filter((row) => wanted.has(row.status));
  const toggle = (status: CountedStatus) =>
    setSelected((current) => (current.includes(status) ? current.filter((item) => item !== status) : [...current, status]));

  return (
    <div className={styles.page}>
      <div role="group" aria-label="Show services by state" className={styles.filters}>
        {COUNTED_STATUSES.map((status) => (
          <button key={status} type="button" className={styles.chip} aria-pressed={selected.includes(status)} onClick={() => toggle(status)}>
            <ShapeIcon shape={STATUS_SHAPES[status]} />
            {`${STATUS_LABELS[status]} (${state.overview.counts[status]})`}
          </button>
        ))}
      </div>
      <p className={styles.note} role="status">
        Listed by name, not ranked.
      </p>
      {rows.length === 0 ? (
        <p className={styles.none}>No service is in this state.</p>
      ) : (
        <ServiceRows label="Services" options={rows.map((row) => capacityToOption(row, state.now))} />
      )}
    </div>
  );
}
