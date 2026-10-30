'use client';

import { useEffect, useState } from 'react';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { leadRead } from '@/lib/lead/browser';
import { clockTime, replayStampText } from '@/lib/lead/format';
import { parseReplayAnswer } from '@/lib/lead/auditParse';
import { statusCodeFor, type AuditReplay as Replay } from '@/lib/lead/audit';
import styles from './Lead.module.css';

// What the advisor saw at a decision (W47). Read-only. The answer is not kept by the browser or the BFF, and
// the back end logs each opening. A refusal and an unknown reference show the same words.

const NO_RECORD = 'No record for that reference.';
const NOT_LOADED = 'The replay could not be loaded. Try again shortly.';

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
      <main className={styles.page}>
        <h1 className={styles.title}>What the advisor saw</h1>
        <p role="alert" className={styles.fieldError}>
          {failure}
        </p>
      </main>
    );
  }
  if (replay === null) {
    return (
      <main className={styles.page}>
        <p className={styles.muted}>Loading the replay.</p>
      </main>
    );
  }

  const timeline = [...replay.timeline].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const versions = [...new Set(replay.criteriaVersions.map((c) => c.version))];
  const allSame = versions.length === 1;

  return (
    <main className={styles.page}>
      <p className={styles.muted}>Audit replay</p>
      <h1 className={styles.title}>What the advisor saw</h1>
      <p className={styles.line}>{`Reference ${replay.reference} · ${replayStampText(replay.decisionAt)}`}</p>

      {!replay.chainOk ? (
        <p role="alert" className={styles.fieldError}>
          This replay did not pass its integrity check. Do not rely on it until it is checked.
        </p>
      ) : null}

      <section className={styles.section} aria-labelledby="replay-shown-heading">
        <h2 id="replay-shown-heading" className={styles.sectionHeading}>
          Services shown
        </h2>
        <ul aria-label="Services shown" className={styles.rows}>
          {replay.shown.map((row) => {
            const code = statusCodeFor(row.status);
            return (
              <li key={row.serviceName} className={styles.row}>
                <strong>{row.serviceName}</strong>
                {code !== null ? <StatusBadge status={code} /> : <span>{row.status}</span>}
                <span>{row.value}</span>
                <span className={styles.muted}>{row.age}</span>
              </li>
            );
          })}
        </ul>
        {allSame ? (
          <p className={styles.line}>{`Criteria version ${versions[0]}`}</p>
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
      <div className={styles.actions}>
        <a
          className={styles.exportLink}
          href={`/api/bff/lead/audit/${encodeURIComponent(reference)}/export`}
          download
          data-el="LEAD-AUDIT-EXPORT-BTN"
        >
          Export for review
        </a>
      </div>
    </main>
  );
}
