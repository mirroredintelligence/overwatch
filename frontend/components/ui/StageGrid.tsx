import type { ReactNode } from 'react';
import styles from './StageGrid.module.css';

// The layout-morph primitive (design canvas provider-onboarding.md, "Shared building blocks"; the motion is
// boards/core-morph/Main.dc.html, renderVals()). One grid with three named areas, list, stage and side. The
// page owns the stage (a number it maps to the URL); a table it gives holds the grid-template-columns of each
// stage, and the columns and the gap animate from one to the next. Inside an area, StageLayer stacks the
// content of each stage: the one that is current is shown, the others fade and drift aside, and are `inert`
// and `aria-hidden` so nothing in them can be tabbed to, read or clicked. Reduced motion needs no code here:
// the duration tokens are zero.

export type StageGridProps = {
  /** The current stage, a whole number from 0. Past either end of `templates`, the nearest one is used. */
  stage: number;
  /** The grid-template-columns of each stage, for example '0px minmax(0,1fr) 340px'. Three tracks: list, stage, side. */
  templates: readonly string[];
  /** The column gap of each stage; one value for all when it has a single entry. Default: --space-5. */
  gaps?: readonly string[];
  /** Extra class for padding and the like. */
  className?: string;
  children: ReactNode;
};

const pick = <T,>(values: readonly T[], stage: number): T => values[Math.min(Math.max(Math.trunc(stage), 0), values.length - 1)];

export function StageGrid({ stage, templates, gaps, className, children }: StageGridProps) {
  const columns = pick(templates, stage);
  const gap = gaps && gaps.length > 0 ? pick(gaps, stage) : 'var(--space-5)';
  return (
    <div
      className={className ? `${styles.grid} ${className}` : styles.grid}
      data-stage={Math.min(Math.max(Math.trunc(stage), 0), templates.length - 1)}
      data-css={JSON.stringify({ gridTemplateColumns: columns, columnGap: gap })}
    >
      {children}
    </div>
  );
}

/** One of the grid's three areas. Its layers are positioned inside it. */
export function StageArea({ name, children }: { name: 'list' | 'stage' | 'side'; children?: ReactNode }) {
  return (
    <div className={styles.area} data-area={name}>
      {children}
    </div>
  );
}

export type StageLayerProps = {
  /** The stage this layer belongs to. */
  index: number;
  /** The grid's current stage. */
  current: number;
  /** `side` layers drift sideways instead of up and down. */
  variant?: 'stage' | 'side';
  children: ReactNode;
};

export function StageLayer({ index, current, variant = 'stage', children }: StageLayerProps) {
  const place = index === current ? 'current' : index < current ? 'before' : 'after';
  const here = place === 'current';
  return (
    <div
      className={styles.layer}
      data-layer={place}
      data-variant={variant}
      inert={!here}
      aria-hidden={here ? undefined : true}
    >
      {children}
    </div>
  );
}
