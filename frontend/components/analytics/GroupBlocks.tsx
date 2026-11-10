'use client';

import { useState } from 'react';
import type { DrillTarget, Group } from '@/lib/analytics/groups';
import { PAGE_SIZE, Pager, pageOf, plural } from './Pager';
import { StatusBar } from './StatusBar';
import styles from './Analytics.module.css';

// Location groups (a row per district) and Service groups (a tile per category), after the Mark design (DEC-1368). Each
// opens the drill-down. A header pill says how many; on a phone a long list shows five at a time. A service that
// covers several districts is counted in each, and one with no district is under "Not placed".

const PHONE_PAGE = 5;

function GroupButton({ group, kind, onOpen }: { group: Group; kind: DrillTarget['kind']; onOpen: (target: DrillTarget) => void }) {
  const n = group.services.length;
  return (
    <button type="button" className={styles.groupButton} data-group={group.key} onClick={() => onOpen({ kind, key: group.key })} disabled={n === 0}>
      <span className={styles.groupTop}>
        <span className={styles.groupName}>
          {group.label}
          {group.sub === undefined ? null : <span className={styles.groupSub}>{group.sub}</span>}
        </span>
        <span className={styles.groupCount}>{`${n} ${plural(n, 'service', 'services')}`}</span>
      </span>
      <StatusBar counts={group.counts} />
    </button>
  );
}

export function LocationGroups({
  groups,
  serviceTotal,
  narrow,
  kind = 'district',
  onOpen,
}: {
  groups: Group[];
  serviceTotal: number;
  narrow: boolean;
  /** `area` when the groups are the organisation's named areas (each service counted once), else postcode districts. */
  kind?: 'district' | 'area';
  onOpen: (target: DrillTarget) => void;
}) {
  const [page, setPage] = useState(0);
  const shown = narrow ? pageOf(groups, page, PHONE_PAGE) : groups;
  return (
    <section className={styles.panel} aria-labelledby="an-locations-heading" data-el="AN-LOCATIONS">
      <div className={styles.blockHead}>
        <h2 id="an-locations-heading" className={styles.panelTitle}>
          Location groups
        </h2>
        <span className={styles.pill} data-el="AN-LOCATIONS-COUNT">{`${serviceTotal} ${plural(serviceTotal, 'service', 'services')}`}</span>
      </div>
      <ul className={styles.locationList}>
        {shown.map((group) => (
          <li key={group.key}>
            <GroupButton group={group} kind={kind} onOpen={onOpen} />
          </li>
        ))}
      </ul>
      <p className={styles.smallNote}>
        {kind === 'area'
          ? 'Each service is counted once, in the area it works in. A service with no place recorded is under Not placed.'
          : 'A service that covers several districts is counted in each. A service with no district recorded is under Not placed.'}
      </p>
      {narrow ? <Pager total={groups.length} page={page} size={PHONE_PAGE} noun="locations" onPage={setPage} /> : null}
    </section>
  );
}

export function ServiceGroups({ groups, narrow, onOpen }: { groups: Group[]; narrow: boolean; onOpen: (target: DrillTarget) => void }) {
  const [page, setPage] = useState(0);
  const shown = narrow ? pageOf(groups, page, PHONE_PAGE) : groups;
  return (
    <section className={styles.panel} aria-labelledby="an-groups-heading" data-el="AN-GROUPS">
      <div className={styles.blockHead}>
        <h2 id="an-groups-heading" className={styles.panelTitle}>
          Service groups
        </h2>
        <span className={styles.pill} data-el="AN-GROUPS-COUNT">{`${groups.length} groups`}</span>
      </div>
      <ul className={styles.groupTiles}>
        {shown.map((group) => (
          <li key={group.key}>
            <GroupButton group={group} kind="group" onOpen={onOpen} />
          </li>
        ))}
      </ul>
      {narrow ? <Pager total={groups.length} page={page} size={PHONE_PAGE} noun="groups" onPage={setPage} /> : null}
    </section>
  );
}

export { PAGE_SIZE };
