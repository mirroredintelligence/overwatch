'use client';

import Link from 'next/link';
import { useState } from 'react';
import { StatusTag } from '@/components/ui/StatusTag';
import { categoryLabel, dataAgeText, durationText } from '@/lib/board/format';
import type { BoardEntry } from '@/lib/board/types';
import { STATUS_TAG, statusWord } from './PlanningStage';
import styles from './ServiceList.module.css';

// Every service on the board (boards/planning/PServices.dc.html), with its status word and its figure. Filter
// chips and a find box narrow the list in place; the order is what needs attention first, then the name, never a
// ranking. The link goes to the service's own page; the list holds no figure beyond the board's.

type Filter = 'all' | 'attention' | 'accepting' | 'limited';

const ATTENTION: ReadonlySet<string> = new Set(['over-capacity', 'not-accepting', 'not-updated']);

// Over capacity, not accepting, not updated, then limited, accepting and the rest.
const RANK: Readonly<Record<string, number>> = {
  'over-capacity': 0,
  'not-accepting': 1,
  'not-updated': 2,
  limited: 3,
  accepting: 4,
};

const rankOf = (entry: BoardEntry) => RANK[entry.status] ?? 5;

export function sortServices(entries: readonly BoardEntry[]): BoardEntry[] {
  return [...entries].sort((a, b) => rankOf(a) - rankOf(b) || a.name.localeCompare(b.name, 'en-GB'));
}

const MATCHES: Readonly<Record<Filter, (entry: BoardEntry) => boolean>> = {
  all: () => true,
  attention: (entry) => ATTENTION.has(entry.status),
  accepting: (entry) => entry.status === 'accepting',
  limited: (entry) => entry.status === 'limited',
};

const CHIPS: readonly { filter: Filter; word: string; glyph?: string }[] = [
  { filter: 'all', word: 'All' },
  { filter: 'attention', word: 'Needs attention' },
  { filter: 'accepting', word: 'Accepting', glyph: '●' },
  { filter: 'limited', word: 'Limited', glyph: '◐' },
];

type Figure = { text: string; meaning: string };

function figureOf(entry: BoardEntry): Figure {
  if (entry.status === 'not-updated') return { text: '?', meaning: 'last known figure not shown' };
  if (entry.overBy !== null && entry.overBy > 0) return { text: `+${entry.overBy}`, meaning: 'over established capacity' };
  if (entry.effectiveAvailable !== null) return { text: String(entry.effectiveAvailable), meaning: entry.unitLabel };
  return { text: '–', meaning: 'no figure' };
}

function lineOf(entry: BoardEntry, now: string): string {
  if (entry.reportedAt === null) return 'No report yet';
  if (entry.status === 'not-updated') {
    const minutes = Math.max(0, Math.floor((Date.parse(now) - Date.parse(entry.reportedAt)) / 60_000));
    return `Last known. Not updated for ${durationText(minutes)}.`;
  }
  return `${categoryLabel(entry.category)} · updated ${dataAgeText(entry.reportedAt, now)}`;
}

export function ServiceList({ entries, now }: { entries: BoardEntry[]; now?: string }) {
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  // The page's clock, from the board; a list built without one reads the time ages from the browser.
  const [mounted] = useState(() => new Date().toISOString());
  const clock = now ?? mounted;

  const sorted = sortServices(entries);
  const needle = query.trim().toLocaleLowerCase('en-GB');
  const shown = sorted.filter((entry) => MATCHES[filter](entry) && entry.name.toLocaleLowerCase('en-GB').includes(needle));
  const count = (which: Filter) => sorted.filter(MATCHES[which]).length;

  return (
    <div className={styles.page}>
      <div className={styles.controls}>
        <div className={styles.chips} role="group" aria-label="Filter the services">
          {CHIPS.map((chip) => (
            <button
              key={chip.filter}
              type="button"
              className={styles.chip}
              aria-pressed={filter === chip.filter}
              onClick={() => setFilter(chip.filter)}
            >
              {chip.glyph ? <span aria-hidden="true">{chip.glyph}</span> : null}
              <span>{chip.word}</span>{' '}
              <span>{count(chip.filter)}</span>
            </button>
          ))}
        </div>
        <div className={styles.find}>
          <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
            <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            className={styles.input}
            aria-label="Find a service"
            placeholder="Find a service"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      {entries.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>There are no services on the board yet.</p>
        </div>
      ) : shown.length === 0 ? (
        <div className={styles.empty}>
          <p role="status" className={styles.emptyTitle}>
            No service matches. Clear the search or choose All.
          </p>
          <button
            type="button"
            className={styles.open}
            onClick={() => {
              setQuery('');
              setFilter('all');
            }}
          >
            {query.trim() === '' ? 'Show all services' : 'Clear the search'}
          </button>
        </div>
      ) : (
        <ul className={styles.card} aria-label="All services">
          {shown.map((entry) => {
            const figure = figureOf(entry);
            return (
              <li key={entry.serviceId} className={styles.row} data-status={entry.status}>
                <div className={styles.text}>
                  <b className={styles.name} data-el="SERVICE-ROW-NAME">
                    {entry.name}
                  </b>
                  <span className={styles.line}>{lineOf(entry, clock)}</span>
                </div>
                <StatusTag variant={STATUS_TAG[entry.status] ?? 'todo'}>{statusWord(entry.status)}</StatusTag>
                <span className={styles.num}>{figure.text}</span>
                <span className={styles.sr}>{figure.meaning}</span>
                <Link
                  href={`/planning/services/${encodeURIComponent(entry.serviceId)}`}
                  className={styles.open}
                  aria-label={`Open ${entry.name}`}
                >
                  Open
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <p className={styles.note}>Sorted by what needs attention first, then by name. Not ranked. No patient information on this screen.</p>
    </div>
  );
}
