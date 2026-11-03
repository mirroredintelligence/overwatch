'use client';

import { useState } from 'react';
import { useAdminRead } from '@/lib/tenantAdmin/browser';
import type { parseLog } from '@/lib/tenantAdmin/views';
import { plainAction, roleWord, whenText } from '@/lib/tenantAdmin/words';
import { TimelineList, type TimelineItem } from '@/components/blocks/TimelineList';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';
import own from './AccessLog.module.css';

// "Who has accessed your organisation" (TEN-076, TEN-084): what the platform's own people did in this
// organisation, read from the organisation's own chain. The role and the step in plain words and the
// reference it was under; never a name or the opaque reference of the person (the BFF has dropped it).

type Log = ReturnType<typeof parseLog>;
type Entry = Log['entries'][number];

const WINDOWS: readonly [number, string][] = [
  [30, 'Last 30 days'],
  [90, 'Last 90 days'],
  [400, 'All'],
];

// The steps where the platform's people were in the organisation's data now: they are the live dots; the rest are past.
const IN_ACCESS = new Set(['OpenCrossTenantAccess', 'UseCrossTenantAccess']);

export function AccessLog() {
  const [days, setDays] = useState(90);
  const { state } = useAdminRead<Log>(`/api/bff/tenant/access-log?days=${days}`);
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Who has accessed your organisation</h1>
      <p className={styles.lede}>What the platform’s own people did in your organisation. You cannot change it.</p>
      <div role="group" aria-label="Show the last" className={own.periods}>
        {WINDOWS.map(([value, word]) => (
          <button key={value} type="button" className={own.period} aria-pressed={days === value} onClick={() => setDays(value)}>
            {word}
          </button>
        ))}
      </div>
      {state.status === 'loading' ? <Loading label="Loading the access log."><SkeletonRows count={3} /></Loading> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the access log.
        </p>
      ) : null}
      {state.status === 'ok' ? <Entries entries={state.data.entries} /> : null}
    </main>
  );
}

function Entries({ entries }: { entries: Log['entries'] }) {
  if (entries.length === 0) {
    return (
      <div className={styles.empty}>
        <p className={styles.text}>Nobody from the platform has accessed your organisation in this time.</p>
      </div>
    );
  }
  const items: TimelineItem[] = entries.map((entry, index) => ({
    id: `${entry.at}-${index}`,
    title: plainAction(entry.useCase),
    detail: detailOf(entry),
    time: whenText(entry.at),
    at: entry.at,
    tone: IN_ACCESS.has(entry.useCase) ? 'normal' : 'past',
  }));
  return (
    <>
      <TimelineList label="Access by the platform’s own people" items={items} />
      <p className={styles.muted}>{`${entries.length} ${entries.length === 1 ? 'step' : 'steps'} shown. The list shows at most 200, newest first.`}</p>
    </>
  );
}

function detailOf(entry: Entry): string {
  const who = roleWord(entry.role);
  return entry.entityIds.length === 0 ? who : `${who} · ref ${entry.entityIds.join(', ')}`;
}
