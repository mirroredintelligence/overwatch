'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { bffGet } from '@/lib/bff/client';
import { parseOverview } from '@/lib/registration/model';
import type { CallBackState, CriteriaState, Overview, ScopeState } from '@/lib/registration/types';
import { CheckList, firstProblem } from './registration/CheckList';
import { useReportFirstProblem } from './registration/RegistrationStage';
import styles from './registration/RegistrationStage.module.css';

// One registration's review overview (W28, ui-screens ApprovalWeb1 screen 3; board Rev1 stage 1). It shows what the
// system checked and, beside it, the checks the shift lead does as a stepper: each row is a link to its own step.
// A check that needs attention never blocks the review: the back end's list of what is missing is the only gate,
// and DecideStep reads it. The first problem is copied to this registration's card in the queue.

type Word = { variant: StatusTagVariant; text: string };

const CALLBACK_WORD: Record<CallBackState, Word> = {
  'not-done': { variant: 'todo', text: 'Not done' },
  done: { variant: 'done', text: 'Done' },
};
const SCOPE_WORD: Record<ScopeState, Word> = {
  'not-done': { variant: 'todo', text: 'Not done' },
  done: { variant: 'done', text: 'Done' },
};
const CRITERIA_WORD: Record<CriteriaState, Word> = {
  'not-done': { variant: 'todo', text: 'Not done' },
  waiting: { variant: 'waiting', text: 'Waiting for the clinical lead' },
  done: { variant: 'done', text: 'Done' },
};

export function RegistrationOverview({ id }: { id: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const report = useReportFirstProblem();

  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await bffGet(`/api/bff/registrations/${encodeURIComponent(id)}`, parseOverview);
      if (!current) return;
      if (result.ok) {
        setOverview(result.data);
        setFailed(false);
        report?.(id, firstProblem(result.data.automaticChecks)?.label ?? null);
      } else {
        setFailed(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [id, attempt, report]);

  if (failed) {
    return (
      <section aria-label="Registration" className={styles.detail}>
        <div className={`${styles.panel} ${styles.error}`}>
          <h2 className={styles.stateTitle}>▲ We could not load this registration</h2>
          <p className={styles.stateText}>
            Nothing has been lost. Check your connection and try again. If it keeps happening, tell the Overwatch team.
          </p>
          <button type="button" className={styles.again} onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      </section>
    );
  }
  if (overview === null) {
    return (
      <section aria-label="Registration" className={styles.detail}>
        <Loading label="Loading the registration.">
          <div className={styles.loadingCard}>
            <Skeleton shape="title" width="40%" />
            <Skeleton shape="line" width="70%" />
            <Skeleton shape="block" />
          </div>
        </Loading>
      </section>
    );
  }

  const { manualChecks } = overview;
  const decideOpen = manualChecks.callback !== 'done' || manualChecks.scope !== 'done' || manualChecks.criteria !== 'done';
  const base = `/lead/registrations/${encodeURIComponent(id)}`;
  const callBack = CALLBACK_WORD[manualChecks.callback];
  const scope = SCOPE_WORD[manualChecks.scope];
  const criteria = CRITERIA_WORD[manualChecks.criteria];

  return (
    <section aria-label="Registration" className={styles.detail}>
      <div className={`${styles.panel} ${styles.overview}`}>
        <div>
          <h1 className={styles.title}>{overview.serviceName}</h1>
          <p className={styles.meta}>
            Registered by {overview.registeredBy.name}, {overview.registeredBy.role}
          </p>
        </div>

        <div className={styles.columns}>
          <CheckList checks={overview.automaticChecks} />

          <section aria-labelledby="registration-steps-heading">
            <h2 id="registration-steps-heading" className={styles.sectionHeading}>
              Checks you do
            </h2>
            <ol className={styles.steps} aria-label="Checks you do">
              <li>
                <a className={styles.step} href={`${base}?step=callback`}>
                  <span className={styles.stepName}>1 Call the service back</span>
                  <StatusTag variant={callBack.variant}>{callBack.text}</StatusTag>
                </a>
              </li>
              <li>
                <a className={styles.step} href={`${base}?step=scope`}>
                  <span className={styles.stepName}>2 Is it in scope?</span>
                  <StatusTag variant={scope.variant}>{scope.text}</StatusTag>
                </a>
              </li>
              <li>
                <div className={`${styles.step} ${styles.stepStatic}`}>
                  <span className={styles.stepName}>3 Criteria second approval</span>
                  <StatusTag variant={criteria.variant}>{criteria.text}</StatusTag>
                </div>
              </li>
              <li>
                <a className={`${styles.step} ${decideOpen ? styles.stepLater : ''}`} href={`${base}?step=decide`}>
                  <span className={styles.stepName}>4 Decide</span>
                  <span className={styles.stepNote}>{decideOpen ? 'Opens when 1 to 3 are done' : 'Ready to decide'}</span>
                </a>
              </li>
            </ol>
          </section>
        </div>

        <div className={styles.actions}>
          <Button variant="primary" href={`${base}?step=callback`} dataEl="LEAD-REG-START-CALLBACK-BTN">
            Start with the call-back
          </Button>
        </div>
      </div>
    </section>
  );
}
