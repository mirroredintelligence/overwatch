'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ShapeIcon, STATUS_SHAPES, type Shape } from '@/components/ui/StatusBadge';
import type { PressureItem, UnderutilisedItem } from '@/lib/lead/types';
import { plural } from './Pager';
import styles from './Analytics.module.css';

// Needs attention (DEC-1343, DEC-1368): one panel, Under pressure beside Underutilised, each with an "N services" pill and
// compact rows: the name (a link to the service page), the share used (or Unknown) and the reason. The lead's rules
// are the back end's: a stale or unknown figure is never in Underutilised, and under pressure it reads Unknown with
// the words to confirm first. Lists are by name. Underutilised is for the viewer to see, not a place to send anyone.

const SHOWN = 5;

type Row = { id: string; name: string; shape: Shape; pill: string; unknown: boolean; detail: string };

function ListCard({ el, countEl, heading, rows, empty, note }: { el: string; countEl: string; heading: string; rows: Row[]; empty: string; note?: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, SHOWN);
  const id = `${el.toLowerCase()}-heading`;
  return (
    <section className={styles.attentionList} aria-labelledby={id} data-el={el}>
      <div className={styles.blockHead}>
        <h3 id={id} className={styles.blockTitle}>
          {heading}
        </h3>
        <span className={styles.pill} data-el={countEl}>{`${rows.length} ${plural(rows.length, 'service', 'services')}`}</span>
      </div>
      {note ? <p className={styles.smallNote}>{note}</p> : null}
      {rows.length === 0 ? (
        <p className={styles.smallNote}>{empty}</p>
      ) : (
        <ul className={styles.attentionRows}>
          {shown.map((row) => (
            <li key={row.id} className={styles.attentionRow}>
              <span className={styles.rowShape}>
                <ShapeIcon shape={row.shape} />
              </span>
              <Link href={`/analytics/services/${encodeURIComponent(row.id)}`} className={styles.link}>
                {row.name}
              </Link>
              <span className={styles.usedPill} data-unknown={row.unknown ? 'true' : undefined}>
                {row.pill}
              </span>
              <span className={styles.reason}>{row.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > SHOWN ? (
        <button type="button" className={styles.more} aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </button>
      ) : null}
    </section>
  );
}

export function AttentionPanel({ underPressure, underutilised }: { underPressure: PressureItem[]; underutilised: UnderutilisedItem[] }) {
  const pressure: Row[] = underPressure.map((item) => ({
    id: item.serviceId,
    name: item.name,
    shape: STATUS_SHAPES[item.status],
    pill: item.usedPercent === null ? 'Unknown' : `${item.usedPercent}% used`,
    unknown: item.usedPercent === null,
    detail: item.reason,
  }));
  const spare: Row[] = underutilised.map((item) => ({
    id: item.serviceId,
    name: item.name,
    shape: STATUS_SHAPES.accepting,
    pill: `${item.usedPercent}% used`,
    unknown: false,
    detail: `${item.spare} ${item.unitLabel}`,
  }));
  return (
    <section className={styles.panel} aria-labelledby="an-attention-heading" data-el="AN-ATTENTION">
      <h2 id="an-attention-heading" className={styles.panelTitle}>
        Needs attention
      </h2>
      <div className={styles.attentionColumns}>
        <ListCard el="AN-PRESSURE" countEl="AN-PRESSURE-COUNT" heading="Under pressure" rows={pressure} empty="No service is under pressure." />
        <ListCard
          el="AN-UNDERUSED"
          countEl="AN-UNDERUSED-COUNT"
          heading="Underutilised"
          rows={spare}
          empty="No service has spare room on a current figure."
          note="Current figures only. This is not a recommendation of where to send a patient."
        />
      </div>
    </section>
  );
}
