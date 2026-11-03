'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { pickAllowed, type ConsoleEvent } from '@/lib/console/allowList';
import { formatMs, formatOffset } from '@/lib/console/trace';
import styles from './Console.module.css';
import own from './SessionTimeline.module.css';

// One session's timeline (W48): element ids, route templates and outcomes only. Field values and page
// text are never recorded, so there is nothing here to show.

export const FILTERS = ['all', 'errors', 'friction', 'api', 'navigation'] as const;
export type Filter = (typeof FILTERS)[number];

const FILTER_LABELS: Record<Filter, string> = {
  all: 'All',
  errors: 'Errors',
  friction: 'Friction',
  api: 'API',
  navigation: 'Navigation',
};

const KIND_LABELS: Record<string, string> = {
  navigation: 'Page view',
  click: 'Click',
  input: 'Input',
  friction: 'Friction',
  api: 'API',
  error: 'Error',
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

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

function describeEvent(event: ConsoleEvent): string {
  return event.elementId ?? event.route ?? '';
}

/** What the selected event was, in plain sentences. Only what was recorded is said. */
function describeSelected(event: ConsoleEvent): string[] {
  const lines: string[] = [];
  if (event.durationMs !== undefined) {
    lines.push(event.kind === 'api' ? `The request took ${formatMs(event.durationMs)}.` : `It took ${formatMs(event.durationMs)}.`);
  }
  const result = event.outcome ?? event.status;
  if (result !== undefined) lines.push(`Outcome: ${result}.`);
  if (lines.length === 0) lines.push('Nothing else was recorded for this event.');
  return lines;
}

export function SessionTimeline({
  sessionId,
  initialEvents,
  initialStandout,
  initialAt,
}: {
  sessionId: string;
  initialEvents: readonly unknown[];
  initialStandout: readonly unknown[];
  /** The offset of the moment the link named (`?at=`), selected when the page opens. */
  initialAt?: number;
}) {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>('all');
  const [events, setEvents] = useState<ConsoleEvent[]>(() => pickAll(initialEvents));
  const [standout, setStandout] = useState<ConsoleEvent[]>(() => pickAll(initialStandout));
  const [picked, setPicked] = useState<number | null>(initialAt ?? null);
  const [error, setError] = useState<string | null>(null);
  const [copyNote, setCopyNote] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);

  // The picked moment when it is still in the list; otherwise the first API call (the usual place to
  // look), otherwise the first event.
  const selected =
    events.find((event) => event.offsetMs === picked) ?? events.find((event) => event.kind === 'api') ?? events[0] ?? null;

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

  async function copyLink() {
    if (selected === null) return;
    const link = `${window.location.origin}/console/session/${encodeURIComponent(sessionId)}?at=${selected.offsetMs}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopyNote('Link copied.');
    } catch {
      setCopyNote('The link could not be copied.');
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
    <main className={own.page}>
      <h1 className={styles.heading}>Session {sessionId}</h1>

      <div className={own.layout}>
        <section className={own.card} aria-labelledby="console-timeline">
          <h2 id="console-timeline" className={own.eyebrow}>
            Timeline
          </h2>
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
          <div className={own.tableWrap}>
            <table className={own.table} aria-label="Timeline">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Element or route</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Duration</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event, index) => {
                  const isSelected = selected !== null && event === selected;
                  const rowClass = [event.kind === 'friction' ? own.friction : '', isSelected ? own.selected : '']
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <tr key={`${event.offsetMs}-${index}`} className={rowClass || undefined}>
                      <td>
                        <button
                          type="button"
                          className={own.press}
                          aria-pressed={isSelected}
                          onClick={() => setPicked(event.offsetMs)}
                        >
                          {formatOffset(event.offsetMs)}
                        </button>
                      </td>
                      <td>
                        {event.kind === 'friction' && (
                          <span className={own.mark} aria-hidden="true">
                            ▲
                          </span>
                        )}
                        {kindLabel(event.kind)}
                      </td>
                      <td className={own.code}>{describeEvent(event)}</td>
                      <td>{event.outcome ?? event.status ?? ''}</td>
                      <td>{event.durationMs === undefined ? '' : formatMs(event.durationMs)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className={own.note}>Events show element ids and outcomes. Field values and page text are never recorded.</p>
        </section>

        <div className={own.side}>
          <section className={`${own.card} ${own.standoutCard}`} aria-labelledby="console-standout">
            <h2 id="console-standout" className={own.eyebrow}>
              What stands out
            </h2>
            {standout.length > 0 ? (
              <ul className={styles.stand}>
                {standout.map((event, index) => (
                  <li key={`${event.offsetMs}-${index}`}>
                    {formatOffset(event.offsetMs)} {kindLabel(event.kind)} {describeEvent(event)}
                  </li>
                ))}
              </ul>
            ) : (
              <p>Nothing stands out in this session.</p>
            )}
          </section>

          <section className={own.card} aria-labelledby="console-selected">
            {selected === null ? (
              <>
                <h2 id="console-selected" className={own.eyebrow}>
                  Selected
                </h2>
                <p>No events were recorded for this session.</p>
              </>
            ) : (
              <>
                <h2 id="console-selected" className={own.eyebrow}>
                  Selected: {formatOffset(selected.offsetMs)} · {kindLabel(selected.kind)}
                </h2>
                <div className={own.lines}>
                  {describeSelected(selected).map((line) => (
                    <p key={line}>{line}</p>
                  ))}
                </div>
                <div className={own.actions}>
                  {selected.kind === 'api' && selected.traceId !== undefined && (
                    <Button
                      variant="primary"
                      href={`/console/trace/${encodeURIComponent(selected.traceId)}?session=${encodeURIComponent(sessionId)}`}
                      dataEl="CON-TL-TRACE-BTN"
                    >
                      View trace
                    </Button>
                  )}
                  {selected.kind === 'api' && selected.traceId === undefined && (
                    <p className={own.note}>No trace recorded for this request.</p>
                  )}
                  <Button variant="secondary" onClick={() => void copyLink()} dataEl="CON-TL-COPY-BTN">
                    Copy link to this moment
                  </Button>
                </div>
                {copyNote !== null && <p role="status" className={own.note}>{copyNote}</p>}
              </>
            )}
          </section>

          <div className={own.actions}>
            <Button variant="neutral" busy={closing} onClick={() => void close()} dataEl="CON-TL-CLOSE-BTN">
              Close session
            </Button>
          </div>
        </div>
      </div>
    </main>
  );
}
