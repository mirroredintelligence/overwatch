'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import styles from './MorphStage.module.css';

// The stage of a guided flow (boards/lead/AddService.dc.html, renderVals()). A thin consumer of the foundation's
// StageGrid: the summary goes in the list area, the steps are layers stacked in the stage area, one current, the
// rest inert and hidden (StageLayer does that). What this adds:
//  - a layer is given as a function and is mounted only once it has been current, so a step that was never
//    reached runs none of its data fetches. A visited layer stays mounted (what was typed is kept, and it can
//    fade out) unless keep="current".
//  - focus moves into the new layer when the step changes: its heading, else the layer itself.
//  - `instant` turns the motion off for one change (Next or Enter from the keyboard is not animated).

export type MorphStageProps = {
  /** The accessible name of the stage region. */
  label: string;
  /** The current step, from 0. The page owns it (state, or the URL). */
  current: number;
  /** The grid-template-columns of each step: three tracks, list, stage, side. */
  templates: readonly string[];
  /** The column gap of each step; see StageGrid. */
  gaps?: readonly string[];
  /** One function per step; called only while that layer is mounted. */
  layers: readonly (() => ReactNode)[];
  /** What to keep mounted: every layer that has been current (default), or only the current one. */
  keep?: 'visited' | 'current';
  /** The pinned summary, for the list area. */
  summary?: ReactNode;
  /** True while the change in progress came from the keyboard: no animation. */
  instant?: boolean;
  className?: string;
};

const clamp = (n: number, count: number) => Math.min(Math.max(Math.trunc(n), 0), Math.max(count - 1, 0));

export function MorphStage({ label, current, templates, gaps, layers, keep = 'visited', summary, instant = false, className }: MorphStageProps) {
  const here = clamp(current, layers.length);
  const [seen, setSeen] = useState<readonly number[]>([here]);
  // Adjusting state while rendering, as React allows: a layer joins the set the first time it is current.
  if (!seen.includes(here)) setSeen([...seen, here]);

  const stageRef = useRef<HTMLDivElement>(null);
  const previous = useRef(here);
  useEffect(() => {
    if (previous.current === here) return;
    previous.current = here;
    const root = stageRef.current;
    const layer = root?.querySelector<HTMLElement>('[data-layer="current"]');
    if (!root || !layer) return;
    const active = document.activeElement;
    if (active && active !== document.body && !root.contains(active)) return;
    const target = layer.querySelector<HTMLElement>('[data-morph-focus], h1, h2') ?? layer;
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  }, [here]);

  return (
    <div className={className ? `${styles.root} ${className}` : styles.root} data-morph="" data-instant={instant ? 'true' : 'false'}>
      <StageGrid stage={here} templates={templates} gaps={gaps} className={styles.grid}>
        <StageArea name="list">{summary}</StageArea>
        <StageArea name="stage">
          <section aria-label={label} className={styles.region} ref={stageRef}>
            {layers.map((render, i) => {
              const mounted = keep === 'current' ? i === here : seen.includes(i);
              return (
                <StageLayer key={i} index={i} current={here}>
                  {mounted ? <div className={styles.content}>{render()}</div> : null}
                </StageLayer>
              );
            })}
          </section>
        </StageArea>
        <StageArea name="side" />
      </StageGrid>
    </div>
  );
}
