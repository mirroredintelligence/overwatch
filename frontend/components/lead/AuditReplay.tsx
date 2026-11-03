'use client';

import { useEffect, useState } from 'react';
import { ShapeIcon, STATUS_SHAPES, type StatusCode } from '@/components/ui/StatusBadge';
import { leadRead } from '@/lib/lead/browser';
import { clockTime } from '@/lib/lead/format';
import { parseReplayAnswer } from '@/lib/lead/auditParse';
import { statusCodeFor, type AuditReplay as Replay } from '@/lib/lead/audit';
import styles from './Audit.module.css';

// What the advisor saw at a decision (W47). Read-only. The answer is not kept by the browser or the BFF, and
// the back end logs each opening. A refusal and an unknown reference show the same words.

const NO_RECORD = 'No record for that reference.';
const NOT_LOADED = 'The replay could not be loaded. Try again shortly.';

const LONDON = 'Europe/London';
const decisionParts = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** "14:13 on Fri 23 Oct", in London time. */
function decisionText(iso: string): string {
  const parts: Record<string, string> = {};
  for (const part of decisionParts.formatToParts(new Date(iso))) parts[part.type] = part.value;
  return `${parts.hour}:${parts.minute} on ${parts.weekday} ${parts.day} ${parts.month}`;
}

// The colour of a status mark; the word always carries the meaning, the colour and shape only support it.
const MARK_COLOUR: Partial<Record<StatusCode, string>> = {
  accepting: styles.markAccepting,
  limited: styles.markLimited,
  'over-capacity': styles.markOver,
  'not-updated': styles.markUnknown,
  'last-known': styles.markUnknown,
};

function StatusMark({ word }: { word: string }) {
  const code = statusCodeFor(word);
  if (code === null) return <span className={styles.mark}>{word}</span>;
  return (
    <span className={`${styles.mark} ${MARK_COLOUR[code] ?? ''}`} data-status={code}>
      <ShapeIcon shape={STATUS_SHAPES[code]} />
      <span>{word}</span>
    </span>
  );
}

export function AuditReplay({ reference }: { reference: string }) {
  const [replay, setReplay] = useState<Replay | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void leadRead(`/api/bff/lead/audit/${encodeURIComponent(reference)}`).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setFailure(result.status === 404 || result.status === 403 ? NO_RECORD : NOT_LOADED);
        return;
      }
      try {
        setReplay(parseReplayAnswer(result.body));
      } catch {
        setFailure(NOT_LOADED);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [reference]);

  if (failure !== null) {
    return (
      <section className={styles.card} aria-labelledby="replay-title">
        <h1 id="replay-title" className={styles.title}>
          What the advisor saw
        </h1>
        <p role="alert" className={styles.fieldError}>
          {failure}
        </p>
      </section>
    );
  }
  if (replay === null) {
    return (
      <section className={styles.card} aria-labelledby="replay-title">
        <h1 id="replay-title" className={styles.title}>
          What the advisor saw
        </h1>
        <p className={styles.muted}>Loading the replay.</p>
      </section>
    );
  }

  const timeline = [...replay.timeline].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const versions = [...new Set(replay.criteriaVersions.map((c) => c.version))];
  const allSame = versions.length === 1;

  return (
    <section className={styles.card} aria-labelledby="replay-title">
      <div className={styles.head}>
        <div className={styles.section}>
          <h1 id="replay-title" className={styles.title}>
            What the advisor saw
          </h1>
          <p className={styles.line}>{`Reference ${replay.reference} · decision at ${decisionText(replay.decisionAt)}`}</p>
        </div>
        <a
          className={styles.exportLink}
          href={`/api/bff/lead/audit/${encodeURIComponent(reference)}/export`}
          download
          data-el="LEAD-AUDIT-EXPORT-BTN"
        >
          Export for the record
        </a>
      </div>

      {replay.chainOk ? (
        <p role="status" className={styles.passed}>
          <svg
            className={styles.bannerIcon}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
            <path d="M8.5 12.5l2.5 2.5 4.5-5" />
          </svg>
          This replay passed its integrity check. Nothing has been changed since it was recorded.
        </p>
      ) : (
        <p role="alert" className={styles.warning}>
          <svg
            className={styles.bannerIcon}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M12 3.5L21.5 20h-19z" />
            <path d="M12 9.5v4.5" />
            <path d="M12 16.8v.1" />
          </svg>
          This replay did not pass its integrity check. Do not rely on it until it is checked.
        </p>
      )}

      <section className={styles.section} aria-labelledby="replay-shown-heading">
        <h2 id="replay-shown-heading" className={styles.sectionHeading}>
          Services shown
        </h2>
        <div className={styles.columns}>
          <span>Service</span>
          <span>Status</span>
          <span>Figure</span>
          <span>Age</span>
        </div>
        <ul aria-label="Services shown" className={styles.rows}>
          {replay.shown.map((row) => (
            <li key={row.serviceName} className={styles.row}>
              <strong className={styles.name}>{row.serviceName}</strong>
              <span data-label="Status">
                <StatusMark word={row.status} />
              </span>
              <span data-label="Figure" className={styles.figure}>
                {row.value}
              </span>
              <span data-label="Age" className={styles.age}>
                {row.age}
              </span>
            </li>
          ))}
        </ul>
        {allSame ? (
          <p className={styles.criteria}>{`Criteria version ${versions[0]} for all services shown.`}</p>
        ) : (
          <ul className={styles.rows} aria-label="Criteria versions">
            {replay.criteriaVersions.map((c) => (
              <li key={c.serviceName}>{`${c.serviceName}: criteria version ${c.version}`}</li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.section} aria-labelledby="replay-timeline-heading">
        <h2 id="replay-timeline-heading" className={styles.sectionHeading}>
          Timeline
        </h2>
        <ol aria-label="Timeline" className={styles.steps}>
          {timeline.map((item) => (
            <li key={`${item.at}-${item.label}`}>
              <time dateTime={item.at}>{clockTime(item.at)}</time> <span>{item.label}</span>
            </li>
          ))}
        </ol>
      </section>

      <p className={styles.muted}>Read-only. Opened for audit, with a log of who looked.</p>
    </section>
  );
}
