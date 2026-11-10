'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { UnderPressureList, UnderutilisedList } from '@/components/lead/PressureLists';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import { BROWSE_STATUSES } from '@/lib/advisor/servicesBrowse';
import { categoryGroups, districtGroups, drillRows, type DrillTarget, type Group } from '@/lib/analytics/groups';
import { parseAnalyticsOverview } from '@/lib/analytics/parse';
import type { AnalyticsOverview as Overview } from '@/lib/analytics/types';
import { categoryLabel } from '@/lib/board/format';
import { StatusBar } from './StatusBar';
import styles from './Analytics.module.css';

// The Analytics User's overview (DEC-1368), after the owner's Mark design (DEC-1343): the five status counts, a card
// per district, a card per service group, what needs attention, and a drill-down to a list of services. It is figures
// only: no total of places available, no patient, no case. A service that covers several districts is counted in each
// of them; one that covers none is under "Not placed". Lists are by name, never ranked by status.

type State = { kind: 'loading' } | { kind: 'ready'; overview: Overview; now: number } | { kind: 'failed' };

const serviceHref = (serviceId: string) => `/analytics/services/${encodeURIComponent(serviceId)}`;

function countOf(overview: Overview, status: StatusCode): number {
  const { counts } = overview;
  const by: Partial<Record<StatusCode, number>> = {
    accepting: counts.accepting,
    limited: counts.limited,
    'not-accepting': counts.notAccepting,
    'over-capacity': counts.overCapacity,
    'not-updated': counts.notUpdated,
  };
  return by[status] ?? 0;
}

function targetWords(target: DrillTarget, overview: Overview): string {
  if (target.kind === 'status') return STATUS_LABELS[target.key as StatusCode];
  if (target.kind === 'group') return categoryLabel(target.key);
  const found = districtGroups(overview.services).find((group) => group.key === target.key);
  return found?.label ?? target.key;
}

function GroupCards({ groups, kind, heading, onOpen, id }: { groups: Group[]; kind: DrillTarget['kind']; heading: string; onOpen: (target: DrillTarget) => void; id: string }) {
  return (
    <section aria-labelledby={`${id}-heading`} data-el={id === 'an-locations' ? 'AN-LOCATIONS' : 'AN-GROUPS'} className={styles.section}>
      <h2 id={`${id}-heading`} className={styles.sectionHeading}>
        {heading}
      </h2>
      <ul className={styles.cards}>
        {groups.map((group) => (
          <li key={group.key}>
            <button type="button" className={styles.card} onClick={() => onOpen({ kind, key: group.key })} disabled={group.services.length === 0}>
              <h3 className={styles.cardName}>{group.label}</h3>
              <p className={styles.cardTotal}>{`${group.services.length} ${group.services.length === 1 ? 'service' : 'services'}`}</p>
              <StatusBar counts={group.counts} />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Drill({ overview, target, now, onBack }: { overview: Overview; target: DrillTarget; now: number; onBack: () => void }) {
  const rows = drillRows(overview.services, target, now);
  const kindWord = target.kind === 'district' ? 'Location' : target.kind === 'group' ? 'Service group' : 'Status';
  return (
    <div className={styles.page}>
      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <button type="button" className={styles.back} onClick={onBack}>
          Back
        </button>
        <ol className={styles.trail}>
          <li>Overview</li>
          <li aria-current="page">{`${kindWord}: ${targetWords(target, overview)}`}</li>
        </ol>
      </nav>
      <p className={styles.note} role="status">{`${rows.length} ${rows.length === 1 ? 'service' : 'services'}. Listed by name, not ranked.${target.kind === 'district' ? ' A service that covers several districts is listed in each.' : ''}`}</p>
      {rows.length === 0 ? (
        <p className={styles.note}>No service here.</p>
      ) : (
        <ul className={styles.rows} data-el="AN-DRILL-LIST">
          {rows.map((row) => (
            <li key={row.serviceId} className={styles.row}>
              <div className={styles.rowText}>
                <h3 className={styles.rowName}>
                  <Link href={row.href}>{row.name}</Link>
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
    </div>
  );
}

export function AnalyticsOverview() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [target, setTarget] = useState<DrillTarget | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/bff/analytics/overview', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('refused');
        const overview = parseAnalyticsOverview(await response.json());
        const stamp = Date.parse(overview.generatedAt);
        setState({ kind: 'ready', overview, now: Number.isNaN(stamp) ? Date.now() : stamp });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'failed' });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === 'loading') {
    return (
      <Loading label="Loading the overview.">
        <Skeleton shape="block" />
      </Loading>
    );
  }
  if (state.kind === 'failed') {
    return <p className={styles.failed}>The overview could not be read. Reload the page to try again.</p>;
  }

  const { overview, now } = state;
  if (target !== null) return <Drill overview={overview} target={target} now={now} onBack={() => setTarget(null)} />;

  return (
    <div className={styles.page}>
      <section aria-labelledby="an-counts-heading" data-el="AN-COUNTS" className={styles.section}>
        <h2 id="an-counts-heading" className={styles.sectionHeading}>
          Services by status
        </h2>
        <ul className={styles.counts}>
          {BROWSE_STATUSES.map((status) => (
            <li key={status}>
              <button type="button" className={styles.count} onClick={() => setTarget({ kind: 'status', key: status })}>
                <span className={styles.shape}>
                  <ShapeIcon shape={STATUS_SHAPES[status]} />
                </span>
                <span className={styles.countWord}>{STATUS_LABELS[status]}</span>
                <span className={styles.countFigure}>{countOf(overview, status)}</span>
              </button>
            </li>
          ))}
        </ul>
        {overview.outOfHours > 0 ? <p className={styles.note}>{`${overview.outOfHours} out of hours, not counted above.`}</p> : null}
      </section>
      <GroupCards id="an-locations" kind="district" heading="Location groups" groups={districtGroups(overview.services)} onOpen={setTarget} />
      <p className={styles.note}>A service that covers several districts is counted in each. A service with no district recorded is under Not placed.</p>
      <GroupCards id="an-groups" kind="group" heading="Service groups" groups={categoryGroups(overview.services)} onOpen={setTarget} />
      <section aria-labelledby="an-attention-heading" className={styles.section}>
        <h2 id="an-attention-heading" className={styles.sectionHeading}>
          Needs attention
        </h2>
        <div className={styles.attention}>
          <UnderPressureList items={overview.underPressure} href={serviceHref} />
          <UnderutilisedList items={overview.underutilised} href={serviceHref} />
        </div>
      </section>
    </div>
  );
}
