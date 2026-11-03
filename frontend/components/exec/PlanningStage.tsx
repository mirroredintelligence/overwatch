import Link from 'next/link';
import type { ReactNode } from 'react';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import { STATUS_LABELS, type StatusCode } from '@/components/ui/StatusBadge';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import styles from './PlanningStage.module.css';

// The planning stage (boards/planning/Morph.dc.html; brief 3, /planning, and 5, Motion). One grid, three states
// that follow the route: `home` (/planning), `service` (/planning/services/[id]) and `alert`
// (/planning/alerts/[id]). The three planning units render into its slots and none of them moves:
//
//   counts        the five status tiles; large at home, folded to a strip after
//   listWide      the Needs-attention list, at home only (the list area)
//   rail          the same list as a narrow rail, at service and alert (the list area)
//   service       the service, on the stage at service and alert (the stage area)
//   sideHome      beside the home: the week glance
//   sideService   beside the service: the alert for it
//   sideAlert     beside the service on the alert: Acknowledge, Call and Snooze
//
// The side column is one area at one place in every state, and the alert's actions are the same three buttons in
// the same order as on the standalone alert page (clinical-safety review, brief 6.2): layout changes only
// because the person chose a service or an alert, never because of a figure. The grid is stacked, one state at a
// time, on a phone.

export type PlanningStageName = 'home' | 'service' | 'alert';

const ORDER: readonly PlanningStageName[] = ['home', 'service', 'alert'];

// The columns of each state: list, stage, side (the board's own).
const TEMPLATES = ['minmax(0,1fr) 0px 340px', '280px minmax(0,1fr) 320px', '260px minmax(0,1fr) 360px'] as const;
const GAPS = ['0px', 'var(--space-5)', 'var(--space-5)'] as const;

type Tile = { status: StatusCode; word: string; glyph: string };

const TILES: readonly Tile[] = [
  { status: 'accepting', word: STATUS_LABELS.accepting, glyph: '●' },
  { status: 'limited', word: STATUS_LABELS.limited, glyph: '◐' },
  { status: 'not-accepting', word: STATUS_LABELS['not-accepting'], glyph: '■' },
  { status: 'over-capacity', word: STATUS_LABELS['over-capacity'], glyph: '▲' },
  { status: 'not-updated', word: STATUS_LABELS['not-updated'], glyph: '◌' },
];

/** The status tag of a service: the shape and the word together, never the colour alone. */
export const STATUS_TAG: Readonly<Record<string, StatusTagVariant>> = {
  accepting: 'done',
  limited: 'waiting',
  'not-accepting': 'closed',
  'over-capacity': 'over',
  'not-updated': 'paused',
};

export function statusWord(status: string): string {
  return STATUS_LABELS[status as StatusCode] ?? status;
}

export type PlanningStageProps = {
  stage: PlanningStageName;
  /** Services by status code; a status with none counts 0. */
  counts: Readonly<Record<string, number>>;
  listWide?: ReactNode;
  rail?: ReactNode;
  service?: ReactNode;
  sideHome?: ReactNode;
  sideService?: ReactNode;
  sideAlert?: ReactNode;
};

/** The index a layer that is shown from stage 1 on takes: current from 1, and waiting after at home. */
const fromService = (stage: number) => (stage === 0 ? 1 : stage);

export function PlanningStage({ stage, counts, listWide, rail, service, sideHome, sideService, sideAlert }: PlanningStageProps) {
  const current = Math.max(0, ORDER.indexOf(stage));
  const compact = current !== 0;
  return (
    <div className={styles.stage} data-planning-stage={stage}>
      <div role="group" aria-label="Services by state" data-compact={compact}>
        <ul className={styles.tiles}>
          {TILES.map((tile) => (
            <li key={tile.status} className={styles.tile} data-status={tile.status}>
              <span className={styles.number}>{counts[tile.status] ?? 0}</span>
              <span className={styles.word}>
                <span aria-hidden="true">{tile.glyph}</span> {tile.word}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <StageGrid stage={current} templates={TEMPLATES} gaps={GAPS} className={styles.grid}>
        <StageArea name="list">
          <section aria-label="Services">
            <StageLayer index={0} current={current}>
              <div className={styles.pad}>{listWide}</div>
            </StageLayer>
            <StageLayer index={fromService(current)} current={current}>
              <div className={styles.pad}>{rail}</div>
            </StageLayer>
          </section>
        </StageArea>
        <StageArea name="stage">
          <StageLayer index={fromService(current)} current={current}>
            <section aria-label="Service" className={styles.pad}>
              {service}
            </section>
          </StageLayer>
        </StageArea>
        <StageArea name="side">
          <aside aria-label="Alongside">
            <StageLayer index={0} current={current} variant="side">
              <div className={styles.pad}>{sideHome}</div>
            </StageLayer>
            <StageLayer index={1} current={current} variant="side">
              <div className={styles.pad}>{sideService}</div>
            </StageLayer>
            <StageLayer index={2} current={current} variant="side">
              <div className={styles.pad}>{sideAlert}</div>
            </StageLayer>
          </aside>
        </StageArea>
      </StageGrid>
    </div>
  );
}

/** The narrow list at the service and the alert: the services that need attention, the open one marked. */
export function AttentionRail({
  entries,
  currentId,
}: {
  entries: readonly { serviceId: string; name: string; status: string }[];
  currentId?: string;
}) {
  return (
    <div className={styles.rail}>
      <div className={styles.eyebrow}>Needs attention</div>
      <ul className={styles.railList} aria-label="Needs attention, in brief">
        {entries.map((entry) => (
          <li key={entry.serviceId}>
            <Link
              href={`/planning/services/${encodeURIComponent(entry.serviceId)}`}
              className={styles.railItem}
              data-status={entry.status}
              aria-current={entry.serviceId === currentId ? 'page' : undefined}
            >
              <span className={styles.railName}>{entry.name}</span>
              <StatusTag variant={STATUS_TAG[entry.status] ?? 'todo'}>{statusWord(entry.status)}</StatusTag>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
