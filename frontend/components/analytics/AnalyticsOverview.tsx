'use client';

import { useEffect, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, type StatusCode } from '@/components/ui/StatusBadge';
import { BROWSE_STATUSES } from '@/lib/advisor/servicesBrowse';
import { areaGroups, categoryGroups, districtGroups, type DrillTarget } from '@/lib/analytics/groups';
import { parseAnalyticsOverview } from '@/lib/analytics/parse';
import type { AnalyticsOverview as Overview } from '@/lib/analytics/types';
import { useNarrow } from '@/lib/analytics/useNarrow';
import { AttentionPanel } from './AttentionPanel';
import { Drill, drillTitle } from './Drill';
import { LocationGroups, ServiceGroups } from './GroupBlocks';
import { plural } from './Pager';
import styles from './Analytics.module.css';

// The Analytics User's overview (DEC-1368), after the owner's Mark design (DEC-1343): the five status counts, Needs
// attention directly under them, Location groups beside Service groups, and a drill-down to a list of services. On a
// phone the last three are tabs (Locations, Attention, Groups) with a short paged list. It is figures only: no total of
// places available, no patient, no case. Status is a shape and a word, never colour alone. Lists are by name.

type State = { kind: 'loading' } | { kind: 'ready'; overview: Overview; now: number } | { kind: 'failed' };
type Tab = 'locations' | 'attention' | 'groups';

const TABS: { key: Tab; label: string }[] = [
  { key: 'locations', label: 'Locations' },
  { key: 'attention', label: 'Attention' },
  { key: 'groups', label: 'Groups' },
];

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

export function AnalyticsOverview() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [target, setTarget] = useState<DrillTarget | null>(null);
  const [tab, setTab] = useState<Tab>('locations');
  const narrow = useNarrow();

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
  const byArea = overview.areas.length > 0;
  const locations = byArea ? areaGroups(overview.services, overview.areas) : districtGroups(overview.services);
  if (target !== null) {
    const title = drillTitle(target, (key) => locations.find((group) => group.key === key)?.label ?? key);
    return <Drill key={`${target.kind}:${target.key}`} overview={overview} target={target} now={now} title={title} onBack={() => setTarget(null)} />;
  }

  const showLocations = !narrow || tab === 'locations';
  const showAttention = !narrow || tab === 'attention';
  const showGroups = !narrow || tab === 'groups';
  const blocks = (
    <>
      {showAttention ? <AttentionPanel underPressure={overview.underPressure} underutilised={overview.underutilised} /> : null}
      <div className={styles.groupRow}>
        {showLocations ? <LocationGroups groups={locations} serviceTotal={overview.services.length} narrow={narrow} kind={byArea ? 'area' : 'district'} onOpen={setTarget} /> : null}
        {showGroups ? <ServiceGroups groups={categoryGroups(overview.services)} narrow={narrow} onOpen={setTarget} /> : null}
      </div>
    </>
  );

  return (
    <div className={styles.page}>
      <section aria-labelledby="an-counts-heading" data-el="AN-COUNTS">
        <h2 id="an-counts-heading" className={styles.srOnly}>
          Services by status
        </h2>
        <ul className={styles.counts}>
          {BROWSE_STATUSES.map((status) => {
            const n = countOf(overview, status);
            return (
              <li key={status}>
                <button type="button" className={styles.count} data-status={status} onClick={() => setTarget({ kind: 'status', key: status })}>
                  <span className={styles.countWord}>
                    <span className={styles.shape}>
                      <ShapeIcon shape={STATUS_SHAPES[status]} />
                    </span>
                    {STATUS_LABELS[status]}
                  </span>
                  <span className={styles.countLine}>
                    <span className={styles.countFigure}>{n}</span>
                    <span className={styles.countUnit}>{plural(n, 'service', 'services')}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {overview.outOfHours > 0 ? <p className={styles.smallNote}>{`${overview.outOfHours} out of hours, not counted above.`}</p> : null}
      </section>
      {narrow ? (
        <div role="tablist" aria-label="Overview sections" className={styles.tabs}>
          {TABS.map((item) => (
            <button key={item.key} type="button" role="tab" id={`an-tab-${item.key}`} aria-selected={tab === item.key} aria-controls="an-tabpanel" className={styles.tab} onClick={() => setTab(item.key)}>
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
      {narrow ? (
        <div role="tabpanel" id="an-tabpanel" aria-labelledby={`an-tab-${tab}`} className={styles.page}>
          {blocks}
        </div>
      ) : (
        blocks
      )}
    </div>
  );
}
