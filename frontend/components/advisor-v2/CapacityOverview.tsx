'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { STATUS_LABELS } from '@/components/ui/StatusBadge';
import { categoryLabel } from '@/lib/board/format';
import { readOverview } from '@/lib/advisor/v2/browser';
import { attentionShown, COUNTED_STATUSES, groupHref, groupsOfRows, statusHref, V2_BROWSE_NOTE, type Overview } from '@/lib/advisor/v2/overview';
import { Dot } from './parts';
import styles from './V2.module.css';

// Capacity (DEC-1366), in the layout of the SPoA design: the five status counts, each a link to its list; a short
// Needs attention card (the shift lead's rules); Underutilised, with the words that it is not a recommendation; and
// one card per service group. A figure that is old shows "Unknown" and says to confirm, never a percentage, and a
// stale figure is never listed as spare capacity. There is no "places available" total (DEC-1343). Nothing here
// opens a case.

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
      <div className={styles.app}>
        <Loading label="Loading the capacity.">
          <Skeleton shape="block" />
        </Loading>
      </div>
    );
  }
  if (state.kind === 'failed') {
    return (
      <div className={styles.app}>
        <p className={styles.failed} role="alert">
          The capacity could not be read. Try again, or open the wall board view.
        </p>
      </div>
    );
  }

  const { overview } = state;
  const pressure = attentionShown(overview.underPressure, overview.attentionShown);
  const room = attentionShown(overview.underutilised, overview.attentionShown);
  const groups = groupsOfRows(overview.services);

  return (
    <div className={styles.app}>
      <div className={styles.titleRow}>
        <h2 className={styles.title}>Regional overview</h2>
        <p className={styles.sub}>{`${overview.services.length} services`}</p>
      </div>
      <ul className={styles.headlines} aria-label="Services by state">
        {COUNTED_STATUSES.map((status) => (
          <li key={status}>
            <Link className={`${styles.panel} ${styles.headline}`} href={statusHref(status)} data-el={`ADV2-COUNT-${status.toUpperCase()}`}>
              <span className={styles.headlineLabel}>
                <Dot status={status} />
                {STATUS_LABELS[status]}
              </span>
              <span className={styles.headlineValue}>{overview.counts[status]}</span>
            </Link>
          </li>
        ))}
      </ul>

      <div className={styles.board}>
        <section aria-labelledby="v2-attention-heading" className={`${styles.panel} ${styles.bottomCard}`}>
          <div className={styles.cardHeading}>
            <h2 id="v2-attention-heading">Needs attention</h2>
            <span className={styles.pill}>{overview.underPressure.length}</span>
          </div>
          {pressure.shown.length === 0 ? (
            <p className={styles.note}>No service is under pressure.</p>
          ) : (
            <ul className={styles.items}>
              {pressure.shown.map((item) => (
                <li key={item.serviceId}>
                  <Link className={styles.item} href={`/advisor/v2/services/${encodeURIComponent(item.serviceId)}`}>
                    <Dot status={item.status} />
                    <span className={styles.itemText}>
                      <strong>{item.name}</strong>
                      <small>{`${STATUS_LABELS[item.status]} · ${item.reason} · ${item.usedPercent === null ? 'Unknown' : `${item.usedPercent}% used`}`}</small>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {pressure.more > 0 ? <p className={styles.note}>{`and ${pressure.more} more`}</p> : null}
        </section>

        <section aria-labelledby="v2-room-heading" className={`${styles.panel} ${styles.bottomCard}`}>
          <div className={styles.cardHeading}>
            <h2 id="v2-room-heading">Underutilised</h2>
            <span className={styles.pill}>{overview.underutilised.length}</span>
          </div>
          <p className={styles.note}>Current figures only. This is not a recommendation of where to send a patient.</p>
          {room.shown.length === 0 ? (
            <p className={styles.note}>No service has spare room on a current figure.</p>
          ) : (
            <ul className={styles.items}>
              {room.shown.map((item) => (
                <li key={item.serviceId}>
                  <Link className={styles.item} href={`/advisor/v2/services/${encodeURIComponent(item.serviceId)}`}>
                    <span className={styles.itemText}>
                      <strong>{item.name}</strong>
                      <small>{`${item.usedPercent}% used · ${item.spare} ${item.unitLabel}`}</small>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {room.more > 0 ? <p className={styles.note}>{`and ${room.more} more`}</p> : null}
        </section>

        <section aria-labelledby="v2-groups-heading" className={`${styles.panel} ${styles.bottomCard} ${styles.groupsCard}`}>
          <h2 id="v2-groups-heading" className={styles.heading}>
            Service groups
          </h2>
          <ul className={styles.groupGrid}>
            {groups.map((group) => (
              <li key={group.category}>
                <Link className={styles.item} href={groupHref(group.category)}>
                  <span className={styles.itemText}>
                    <strong>{categoryLabel(group.category)}</strong>
                  </span>
                  <span className={styles.pill}>{group.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <p className={styles.footer}>{V2_BROWSE_NOTE}</p>
    </div>
  );
}
