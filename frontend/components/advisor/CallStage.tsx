'use client';

import { type ReactNode, useEffect, useRef } from 'react';
import { StageArea, StageGrid } from '@/components/ui/StageGrid';
import styles from './CallStage.module.css';

// The grid of a call (advisor-clinical-wall.md section 3; boards/advisor/Call.dc.html): summary | stage | side
// over the foundation StageGrid. The page owns the stage (it maps it to the URL). The columns per stage are
// the board's: the summary is folded away before the options and the side on the options. A folded column is
// `inert` and `aria-hidden`, so nothing in it can be tabbed to or read. When the person moves to another stage
// focus goes to the stage heading, so a reader lands on what changed; the first render never takes focus.

export type CallStageName = 'overview' | 'needs' | 'options' | 'request';

const ORDER: readonly CallStageName[] = ['overview', 'needs', 'options', 'request'];

const TEMPLATES = [
  '0px minmax(0,1fr) 340px',
  '0px minmax(0,1fr) 320px',
  '300px minmax(0,1fr) 0px',
  '270px minmax(0,1fr) 300px',
] as const;

const GAPS = ['0px', '0px', 'var(--space-5)', 'var(--space-5)'] as const;

export type CallStageProps = {
  step: CallStageName;
  /** The pinned patient card; shown from the options on. */
  summary?: ReactNode;
  /** What sits alongside the stage; shown on the overview, needs and request. */
  side?: ReactNode;
  /** The stage itself. */
  children: ReactNode;
};

export function CallStage({ step, summary, side, children }: CallStageProps) {
  const index = ORDER.indexOf(step);
  const summaryFolded = index < 2;
  const sideFolded = index === 2;
  const stageRef = useRef<HTMLDivElement>(null);
  const previous = useRef(step);

  useEffect(() => {
    if (previous.current === step) return;
    previous.current = step;
    const heading = stageRef.current?.querySelector<HTMLElement>('h1, h2');
    if (!heading) return;
    if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: true });
  }, [step]);

  return (
    <StageGrid stage={index} templates={TEMPLATES} gaps={GAPS} className={styles.grid}>
      <StageArea name="list">
        <div
          className={`${styles.fold} ${styles.foldList}`}
          inert={summaryFolded}
          aria-hidden={summaryFolded ? true : undefined}
          data-folded={summaryFolded}
        >
          {summary}
        </div>
      </StageArea>
      <StageArea name="stage">
        <div ref={stageRef} className={styles.stage} data-el="ADV-CALL-STAGE">
          {children}
        </div>
      </StageArea>
      <StageArea name="side">
        <div
          className={`${styles.fold} ${styles.foldSide}`}
          inert={sideFolded}
          aria-hidden={sideFolded ? true : undefined}
          data-folded={sideFolded}
        >
          <aside aria-label="Alongside">{side}</aside>
        </div>
      </StageArea>
    </StageGrid>
  );
}
