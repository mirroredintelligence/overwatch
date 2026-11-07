'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { invitedAs } from '@/lib/lead/invitations';
import { SETUP_STEPS, stuckAt } from '@/lib/lead/setupProgress';
import type { Invitation } from './SetupTracker';
import styles from './ReporterList.module.css';

// The list of invited reporters (INV-01): a ul of buttons, one per invitation, with the status as shape plus
// word, a bar of seven segments (one per set-up step) and filter chips that work on the list already loaded.
// The open reporter's row has aria-current.

export type ReporterStatus = 'stuck' | 'progress' | 'invited' | 'complete';

/** A set-up that is not complete and has not been seen for this long is stuck. */
const STUCK_AFTER_MS = 30 * 60_000;

/** Complete when every step is done; stuck when not seen for half an hour; otherwise invited or in progress. */
export function reporterStatus(item: Invitation, now: number): ReporterStatus {
  if (stuckAt(item.steps) === null) return 'complete';
  const seen = Date.parse(item.lastSeen);
  if (Number.isNaN(seen) || now - seen > STUCK_AFTER_MS) return 'stuck';
  return SETUP_STEPS.every((step) => step === 'invited' || !item.steps[step]) ? 'invited' : 'progress';
}

export function stepsDone(item: Invitation): number {
  return SETUP_STEPS.filter((step) => item.steps[step]).length;
}

const WORD: Record<ReporterStatus, string> = { stuck: 'Stuck', progress: 'In progress', invited: 'Invited', complete: 'Complete' };
const SHAPE: Record<ReporterStatus, StatusTagVariant> = { stuck: 'problem', progress: 'done', invited: 'todo', complete: 'confirmed' };

type Filter = 'all' | 'stuck' | 'progress' | 'complete';

const CHIPS: readonly { filter: Filter; label: string; none: string }[] = [
  { filter: 'all', label: 'All', none: '' },
  { filter: 'stuck', label: 'Stuck', none: 'No set-up is stuck.' },
  { filter: 'progress', label: 'In progress', none: 'No set-up is in progress.' },
  { filter: 'complete', label: 'Complete', none: 'No set-up is complete.' },
];

function matches(filter: Filter, status: ReporterStatus): boolean {
  if (filter === 'all') return true;
  if (filter === 'progress') return status === 'progress' || status === 'invited';
  return filter === status;
}

export type ReporterListProps = {
  items: readonly Invitation[];
  /** Epoch ms, fixed by the page so every row is judged against the same moment. */
  now: number;
  /** The invitation open beside the list, or null. */
  currentId: string | null;
  onOpen: (id: string) => void;
};

export function ReporterList({ items, now, currentId, onOpen }: ReporterListProps) {
  const [filter, setFilter] = useState<Filter>('all');
  const shown = items.filter((item) => matches(filter, reporterStatus(item, now)));
  const none = CHIPS.find((chip) => chip.filter === filter)?.none ?? '';

  return (
    <section className={styles.list} aria-label="Set-up progress">
      <div className={styles.head}>
        <h2 className={styles.heading}>Set-up progress</h2>
        <Button variant="secondary" href="/lead/reporters/invite" dataEl="LEAD-TRACK-INVITE-BTN">
          Invite
        </Button>
      </div>
      <div className={styles.chips} role="group" aria-label="Show">
        {CHIPS.map((chip) => (
          <button
            key={chip.filter}
            type="button"
            className={styles.chip}
            aria-pressed={filter === chip.filter}
            onClick={() => setFilter(chip.filter)}
          >
            {chip.label}
          </button>
        ))}
      </div>
      {shown.length === 0 && items.length > 0 ? <p className={styles.none}>{none}</p> : null}
      {shown.length > 0 ? (
        <ul className={styles.rows}>
          {shown.map((item) => {
            const status = reporterStatus(item, now);
            const waiting = stuckAt(item.steps);
            const done = stepsDone(item);
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={styles.row}
                  data-status={status}
                  aria-current={item.id === currentId ? 'true' : undefined}
                  onClick={() => onOpen(item.id)}
                >
                  <span className={styles.bar} role="img" aria-label={`${done} of ${SETUP_STEPS.length} steps done`}>
                    {SETUP_STEPS.map((step) => (
                      <span key={step} className={styles.segment} data-done={item.steps[step]} />
                    ))}
                  </span>
                  <span className={styles.text}>
                    <span className={styles.name}>{item.serviceName}</span>
                    <span className={styles.role}>{invitedAs(item)}</span>
                    {status !== 'complete' && waiting !== null ? <span className={styles.waiting}>{`Waiting at: ${waiting}`}</span> : null}
                  </span>
                  <StatusTag variant={SHAPE[status]}>{WORD[status]}</StatusTag>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
