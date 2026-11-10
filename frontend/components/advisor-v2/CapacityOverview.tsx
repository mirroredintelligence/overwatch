'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, StatusBadge } from '@/components/ui/StatusBadge';
import { readOverview } from '@/lib/advisor/v2/browser';
import { attentionShown, COUNTED_STATUSES, statusHref, V2_BROWSE_NOTE, type Overview } from '@/lib/advisor/v2/overview';
import styles from './V2.module.css';

// Capacity (DEC-1366): the five status counts, each a link to a list of those services, and a short Needs attention
// list, from the shift lead's rules. A figure that is old shows "Unknown" and says to confirm, never a percentage,
// and a stale figure is never listed as spare capacity. Underutilised is not a recommendation of where to send a
// patient. Nothing here opens a case.

type State = { kind: 'loading' } | { kind: 'ready'; overview: Overview } | { kind: 'failed' };

export function CapacityOverview() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    let live = true;
    readOverview().then((overview) => {
      if (live) setState(overview === null ? { kind: 'failed' } : { kind: 'ready', overview });
    });
    return () => {
      live = false;
    };
  }, []);

  if (state.kind === 'loading') {
    return (
      <Loading label="Loading the capacity.">
        <Skeleton shape="block" />
      </Loading>
    );
  }
  if (state.kind === 'failed') {
    return (
      <p className={styles.failed} role="alert">
        The capacity could not be read. Try again, or open the wall board view.
      </p>
    );
  }

  const { overview } = state;
  const pressure = attentionShown(overview.underPressure, overview.attentionShown);
  const room = attentionShown(overview.underutilised, overview.attentionShown);

  return (
    <div className={styles.page}>
      <p className={styles.note}>{V2_BROWSE_NOTE}</p>
      <ul className={styles.counts} aria-label="Services by state">
        {COUNTED_STATUSES.map((status) => (
          <li key={status}>
            <Link className={styles.count} href={statusHref(status)} data-el={`ADV2-COUNT-${status.toUpperCase()}`}>
              <span className={styles.countNumber}>{overview.counts[status]}</span>
              <span className={styles.countWord}>
                <ShapeIcon shape={STATUS_SHAPES[status]} />
                {STATUS_LABELS[status]}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <div className={styles.two}>
        <section aria-labelledby="v2-attention-heading" className={styles.card}>
          <h2 id="v2-attention-heading" className={styles.heading}>
            Needs attention
          </h2>
          {pressure.shown.length === 0 ? (
            <p className={styles.none}>No service is under pressure.</p>
          ) : (
            <ul className={styles.attention}>
              {pressure.shown.map((item) => (
                <li key={item.serviceId} className={styles.attentionRow}>
                  <Link className={styles.attentionName} href={`/advisor/v2/services/${encodeURIComponent(item.serviceId)}`}>
                    {item.name}
                  </Link>
                  <StatusBadge status={item.status} />
                  <span className={styles.small}>
                    {`${item.reason} · ${item.usedPercent === null ? 'Unknown' : `${item.usedPercent}% used`}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {pressure.more > 0 ? <p className={styles.small}>{`and ${pressure.more} more`}</p> : null}
        </section>

        <section aria-labelledby="v2-room-heading" className={styles.card}>
          <h2 id="v2-room-heading" className={styles.heading}>
            Underutilised
          </h2>
          <p className={styles.small}>Current figures only. This is not a recommendation of where to send a patient.</p>
          {room.shown.length === 0 ? (
            <p className={styles.none}>No service has spare room on a current figure.</p>
          ) : (
            <ul className={styles.attention}>
              {room.shown.map((item) => (
                <li key={item.serviceId} className={styles.attentionRow}>
                  <Link className={styles.attentionName} href={`/advisor/v2/services/${encodeURIComponent(item.serviceId)}`}>
                    {item.name}
                  </Link>
                  <span className={styles.small}>{`${item.usedPercent}% used · ${item.spare} ${item.unitLabel}`}</span>
                </li>
              ))}
            </ul>
          )}
          {room.more > 0 ? <p className={styles.small}>{`and ${room.more} more`}</p> : null}
        </section>
      </div>
    </div>
  );
}
