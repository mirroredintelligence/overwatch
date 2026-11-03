import type { ReactNode } from 'react';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import styles from './ReporterStage.module.css';

// The one page the three reporter routes become (INV-01; used by the invite and number pages too): the list
// never goes away, and the stage area holds the compose panel or the detail. The page owns the state, from its
// address. "number" is the detail with its change-number row open, so it shares the detail's layer.
//
//   browse   list full width, stage collapsed          compose  list 420px, stage = the compose panel
//   detail   list 340px, stage = the timeline+actions  number   the same columns as detail

export type ReporterStageState = 'browse' | 'compose' | 'detail' | 'number';

const STAGES: readonly ReporterStageState[] = ['browse', 'compose', 'detail', 'number'];

const TEMPLATES = ['minmax(0,1fr) 0px 0px', '420px minmax(0,1fr) 0px', '340px minmax(0,1fr) 0px', '340px minmax(0,1fr) 0px'];
const GAPS = ['0px', '22px', '22px', '22px'];

export type ReporterStageProps = {
  state: ReporterStageState;
  list: ReactNode;
  compose?: ReactNode;
  detail?: ReactNode;
};

export function ReporterStage({ state, list, compose, detail }: ReporterStageProps) {
  const stage = STAGES.indexOf(state);
  return (
    <StageGrid stage={stage} templates={TEMPLATES} gaps={GAPS} className={styles.grid}>
      <StageArea name="list">
        <div className={styles.list}>{list}</div>
      </StageArea>
      <StageArea name="stage">
        <StageLayer index={1} current={stage}>
          {compose}
        </StageLayer>
        <StageLayer index={state === 'number' ? 3 : 2} current={stage}>
          {detail}
        </StageLayer>
      </StageArea>
      <StageArea name="side" />
    </StageGrid>
  );
}
