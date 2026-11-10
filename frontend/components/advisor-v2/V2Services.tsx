'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { STATUS_LABELS } from '@/components/ui/StatusBadge';
import { categoryLabel } from '@/lib/board/format';
import { readOverview } from '@/lib/advisor/v2/browser';
import { capacityToOption, COUNTED_STATUSES, type CountedStatus, type Overview } from '@/lib/advisor/v2/overview';
import { Dot, PagedGrid, ServiceTile } from './parts';
import styles from './V2.module.css';

// The services of one state or more, or of one service group (DEC-1366), opened from a count or a group on Capacity.
// By name, never by status, in pages that fit the screen. A late or old figure reads "Current capacity
// unavailable". Each tile links to the service's page. The breadcrumb leads back to Capacity.

type State = { kind: 'loading' } | { kind: 'ready'; overview: Overview; now: number } | { kind: 'failed' };

export function V2Services({ initial, group, district }: { initial: CountedStatus[]; group: string | null; district: string | null }) {
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
      <div className={styles.app}>
        <Loading label="Loading the services.">
          <Skeleton shape="block" />
        </Loading>
      </div>
    );
  }
  if (state.kind === 'failed') {
    return (
      <div className={styles.app}>
        <p className={styles.failed} role="alert">
          The services could not be read. Try again.
        </p>
      </div>
    );
  }

  const wanted = new Set<string>(selected.length === 0 ? COUNTED_STATUSES : selected);
  const rows = state.overview.services.filter((row) => wanted.has(row.status) && (group === null || row.category === group) && (district === null || (district === 'none' ? row.districts.length === 0 : row.districts.includes(district))));
  const toggle = (status: CountedStatus) =>
    setSelected((current) => (current.includes(status) ? current.filter((item) => item !== status) : [...current, status]));

  return (
    <div className={styles.app}>
      <nav className={styles.crumbs} aria-label="Breadcrumb">
        <Link href="/advisor/v2?mode=capacity">Capacity</Link>
        <span aria-hidden="true">›</span>
        <span aria-current="page">{group !== null ? categoryLabel(group) : district !== null ? (district === 'none' ? 'Not placed' : district) : 'Services'}</span>
      </nav>
      <div className={`${styles.panel} ${styles.listPanel}`}>
        <div className={styles.filterBar} role="group" aria-label="Show services by state">
          {COUNTED_STATUSES.map((status) => (
            <button key={status} type="button" className={styles.choice} aria-pressed={selected.includes(status)} onClick={() => toggle(status)}>
              <Dot status={status} /> {`${STATUS_LABELS[status]} (${state.overview.counts[status]})`}
            </button>
          ))}
        </div>
        <p className={styles.note} role="status">
          Listed by name, not ranked.
        </p>
        <PagedGrid
          items={rows.map((row) => capacityToOption(row, state.now))}
          keyOf={(item) => item.serviceId}
          label="Services"
          noun="services"
          empty="No service is in this state."
          render={(item) => <ServiceTile option={item} />}
        />
      </div>
    </div>
  );
}
