'use client';

import Link from 'next/link';
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { StageArea, StageGrid } from '@/components/ui/StageGrid';
import { RegistrationQueue } from '../RegistrationQueue';
import styles from './RegistrationStage.module.css';

// The review of a registration as one stage (provider-onboarding.md Journey 4; board Rev1). The queue is the list
// and the registration is the stage; when one opens the queue narrows and the registration takes the room. The
// route owns the stage number (0 queue, 1 overview, 2 call back, 3 scope, 4 decide, 5 go live) and the content
// of the stage area; this component owns the grid, the queue and the one thing they share: the first automatic
// problem of the open registration, which the overview reports and the queue card shows.

const TEMPLATES = [
  'minmax(0,1fr) 0px 0px',
  '380px minmax(0,1fr) 0px',
  '300px minmax(0,1fr) 0px',
  '300px minmax(0,1fr) 0px',
  '300px minmax(0,1fr) 0px',
  '300px minmax(0,1fr) 0px',
] as const;

// The space between the queue and the registration is padding inside the stage area, so a closed (0px) track
// takes no room at all.
const GAPS = ['0px'] as const;

type Report = (id: string, problem: string | null) => void;

const ProblemContext = createContext<Report | undefined>(undefined);

/** For the overview: tell the stage a registration's first problem (or `null` for none). Undefined outside a stage. */
export function useReportFirstProblem(): Report | undefined {
  return useContext(ProblemContext);
}

export function RegistrationStage({
  stage,
  selectedId,
  children,
}: {
  stage: number;
  selectedId?: string;
  children?: ReactNode;
}) {
  const [problems, setProblems] = useState<Readonly<Record<string, string>>>({});
  const report = useCallback<Report>((id, problem) => {
    setProblems((previous) => {
      if (problem === null) {
        if (!(id in previous)) return previous;
        const next = { ...previous };
        delete next[id];
        return next;
      }
      return previous[id] === problem ? previous : { ...previous, [id]: problem };
    });
  }, []);

  // The queue and the overview are the page when no check is open; a check draws its own heading and landmark.
  const ownsPage = stage <= 1;

  return (
    <ProblemContext.Provider value={report}>
      <div className={styles.stage} role={ownsPage ? 'main' : undefined}>
        {stage === 0 ? <PageHeader title="Registrations" /> : null}
        <StageGrid stage={stage} templates={TEMPLATES} gaps={GAPS} className={styles.shell}>
          <StageArea name="list">
            <div className={styles.listInner}>
              <RegistrationQueue selectedId={selectedId} problems={problems} />
            </div>
          </StageArea>
          <StageArea name="stage">
            <div className={styles.stageInner}>
              {stage > 0 ? (
                <Link className={styles.back} href="/lead/registrations">
                  Back to registrations
                </Link>
              ) : null}
              {children}
            </div>
          </StageArea>
        </StageGrid>
      </div>
    </ProblemContext.Provider>
  );
}
