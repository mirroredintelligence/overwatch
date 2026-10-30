'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { pickAllowed, type ConsoleEvent } from '@/lib/console/allowList';
import { formatMs, formatOffset } from '@/lib/console/trace';
import styles from './Console.module.css';

// One session's timeline (W48): element ids, route templates and outcomes only. Field values and
// page text are never recorded, so there is nothing here to show.

export const FILTERS = ['all', 'errors', 'friction', 'api', 'navigation'] as const;
export type Filter = (typeof FILTERS)[number];

const FILTER_LABELS: Record<Filter, string> = {
  all: 'All',
  errors: 'Errors',
  friction: 'Friction',
  api: 'API',
  navigation: 'Navigation',
};

function pickAll(raw: readonly unknown[]): ConsoleEvent[] {
  const kept: ConsoleEvent[] = [];
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue;
    const event = pickAllowed(item as Record<string, unknown>);
    if (event !== null) kept.push(event);
  }
  return kept;
}

function describeEvent(event: ConsoleEvent): string {
  return event.elementId ?? event.route ?? '';
}

export function SessionTimeline({
  sessionId,
  initialEvents,
  initialStandout,
}: {
  sessionId: string;
  initialEvents: readonly unknown[];
  initialStandout: readonly unknown[];
}) {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>('all');
  const [events, setEvents] = useState<ConsoleEvent[]>(() => pickAll(initialEvents));
  const [standout, setStandout] = useState<ConsoleEvent[]>(() => pickAll(initialStandout));
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);

  async function choose(next: Filter) {
    setFilter(next);
    setError(null);
    try {
      const response = await fetch(
        `/api/bff/console/sessions/${encodeURIComponent(sessionId)}/events?filter=${next}`,
        { credentials: 'same-origin' },
      );
      if (!response.ok) {
        setError(response.status === 403 ? 'You do not have access to the console.' : 'The timeline could not be loaded.');
        return;
      }
      const body = (await response.json()) as { events?: unknown[]; standout?: unknown[] };
      setEvents(pickAll(body.events ?? []));
      setStandout(pickAll(body.standout ?? []));
    } catch {
      setError('The timeline could not be loaded.');
    }
  }

  async function close() {
    setClosing(true);
    try {
      const response = await fetch(`/api/bff/console/sessions/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!response.ok) {
        setError('Access could not be closed. Try again.');
        return;
      }
      router.push('/console');
    } finally {
      setClosing(false);
    }
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Session {sessionId}</h1>

      {standout.length > 0 && (
        <section className={styles.section} aria-labelledby="console-standout">
          <h2 id="console-standout" className={styles.heading}>What stands out</h2>
          <ul className={styles.stand}>
            {standout.map((event, index) => (
              <li key={`${event.offsetMs}-${index}`}>
                {formatOffset(event.offsetMs)} {event.kind} {describeEvent(event)}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={styles.section} aria-labelledby="console-timeline">
        <h2 id="console-timeline" className={styles.heading}>Timeline</h2>
        <div className={styles.chips} role="group" aria-label="Filter the timeline">
          {FILTERS.map((name) => (
            <Chip
              key={name}
              pressed={filter === name}
              onPressedChange={() => void choose(name)}
              dataEl={`CON-TL-FILTER-${name.toUpperCase()}`}
            >
              {FILTER_LABELS[name]}
            </Chip>
          ))}
        </div>
        {error !== null && <p role="alert" className={styles.alert}>{error}</p>}
        <table className={styles.table} aria-label="Timeline">
          <thead>
            <tr>
              <th scope="col">Offset</th>
              <th scope="col">Kind</th>
              <th scope="col">Element or route</th>
              <th scope="col">Outcome</th>
              <th scope="col">Duration</th>
              <th scope="col">Trace</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event, index) => (
              <tr key={`${event.offsetMs}-${index}`}>
                <td>{formatOffset(event.offsetMs)}</td>
                <td>{event.kind}</td>
                <td>{describeEvent(event)}</td>
                <td>{event.outcome ?? event.status ?? ''}</td>
                <td>{event.durationMs === undefined ? '' : formatMs(event.durationMs)}</td>
                <td>
                  {event.kind === 'api' && event.traceId !== undefined ? (
                    <Link href={`/console/trace/${event.traceId}`} data-el="CON-TL-TRACE-BTN">
                      View trace
                    </Link>
                  ) : event.kind === 'api' ? (
                    'No trace recorded'
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div>
        <Button variant="neutral" busy={closing} onClick={() => void close()} dataEl="CON-TL-CLOSE-BTN">
          Close session
        </Button>
      </div>
    </main>
  );
}
