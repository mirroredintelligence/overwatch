'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, StatusBadge } from '@/components/ui/StatusBadge';
import { BROWSE_STATUSES } from '@/lib/advisor/servicesBrowse';
import { drillRows, inTarget, statusCounts, type DrillTarget } from '@/lib/analytics/groups';
import type { AnalyticsOverview } from '@/lib/analytics/types';
import { categoryLabel } from '@/lib/board/format';
import { PAGE_SIZE, Pager, pageOf, plural } from './Pager';
import styles from './Analytics.module.css';

// The drill-down (DEC-1368): the services of one district, group or status, after the Mark design. The heading is the
// name with an "N services" pill; under it a strip of the five status counts of the set (a shape and a word each);
// then the services by name in a two-column grid, six to a page. An old or late figure reads "Current capacity
// unavailable", never a number. Each name links to the service page.

const KIND_WORDS: Record<DrillTarget['kind'], string> = { district: 'Location', group: 'Service group', status: 'Status' };

export function drillTitle(target: DrillTarget, labelOfDistrict: (key: string) => string): string {
  if (target.kind === 'status') return STATUS_LABELS[target.key as keyof typeof STATUS_LABELS] ?? target.key;
  if (target.kind === 'group') return categoryLabel(target.key);
  return labelOfDistrict(target.key);
}

export function Drill({ overview, target, now, title, onBack }: { overview: AnalyticsOverview; target: DrillTarget; now: number; title: string; onBack: () => void }) {
  const [page, setPage] = useState(0);
  const rows = drillRows(overview.services, target, now);
  const tally = statusCounts(overview.services.filter((service) => inTarget(service, target)));
  const shown = pageOf(rows, page, PAGE_SIZE);
  return (
    <div className={styles.page}>
      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <button type="button" className={styles.back} onClick={onBack}>
          Back
        </button>
        <ol className={styles.trail}>
          <li>Overview</li>
          <li aria-current="page">{`${KIND_WORDS[target.kind]}: ${title}`}</li>
        </ol>
      </nav>
      <section className={styles.panel} aria-labelledby="an-drill-heading">
        <div className={styles.blockHead}>
          <h2 id="an-drill-heading" className={styles.drillTitle}>
            {title}
          </h2>
          <span className={styles.pill} data-el="AN-DRILL-COUNT">{`${rows.length} ${plural(rows.length, 'service', 'services')}`}</span>
        </div>
        <ul className={styles.strip} data-el="AN-DRILL-STRIP">
          {BROWSE_STATUSES.map((status) => (
            <li key={status} className={styles.stripItem}>
              <span className={styles.shape}>
                <ShapeIcon shape={STATUS_SHAPES[status]} />
              </span>
              <span className={styles.stripNumber}>{tally[status as keyof typeof tally]}</span>
              <span className={styles.stripWord}>{STATUS_LABELS[status]}</span>
            </li>
          ))}
        </ul>
        <p className={styles.smallNote}>{`Listed by name, not ranked.${target.kind === 'district' ? ' A service that covers several districts is listed in each.' : ''}`}</p>
        {rows.length === 0 ? (
          <p className={styles.smallNote}>No service here.</p>
        ) : (
          <ul className={styles.rows} data-el="AN-DRILL-LIST">
            {shown.map((row) => (
              <li key={row.serviceId} className={styles.row}>
                <div className={styles.rowText}>
                  <h3 className={styles.rowName}>
                    <Link href={row.href} className={styles.link}>
                      {row.name}
                    </Link>
                  </h3>
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
        <Pager total={rows.length} page={page} size={PAGE_SIZE} noun="services" onPage={setPage} />
      </section>
    </div>
  );
}
