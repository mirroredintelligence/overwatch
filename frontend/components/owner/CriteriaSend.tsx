'use client';

import { useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffPost } from '@/lib/bff/client';
import { REASON_MAX_LENGTH, REVIEW_PERIODS, reasonError, reviewPeriodError } from '@/lib/criteria/model';
import type { CriteriaValues, ReviewPeriod } from '@/lib/criteria/types';
import styles from './CriteriaSend.module.css';
import { CriteriaStatus } from './CriteriaStatus';

// "Send for second approval" (W30, ui-screens CriteriaOwner screen 6, boards/lead/OwnerReview.dc.html step 5). The
// change is sent with its reason and review period. The status tracker takes over once the back end has taken it.

export function CriteriaSend({
  serviceId,
  currentVersion,
  changes,
  values,
}: {
  serviceId: string;
  currentVersion: number;
  changes: string[];
  values: CriteriaValues;
}) {
  const ids = useId();
  const [reason, setReason] = useState('');
  const [months, setMonths] = useState<ReviewPeriod | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<{ version: number; sentAt: string } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const send = async () => {
    const found: Record<string, string> = {};
    const reasonProblem = reasonError(reason);
    const periodProblem = reviewPeriodError(months);
    if (reasonProblem !== null) found.reason = reasonProblem;
    if (periodProblem !== null) found.months = periodProblem;
    setErrors(found);
    if (Object.keys(found).length > 0 || months === null) return;
    setBusy(true);
    setFailure(null);
    const trimmed = reason.trim();
    const result = await bffPost(`/api/bff/criteria/${encodeURIComponent(serviceId)}/submit`, {
      ...values,
      reason: trimmed,
      reviewInMonths: months,
    });
    setBusy(false);
    if (result.ok) {
      const version = (result.data as { version?: unknown } | undefined)?.version;
      setSent({ version: typeof version === 'number' ? version : currentVersion + 1, sentAt: new Date().toISOString() });
    } else {
      setFailure('The change was not sent. Check it and try again.');
    }
  };

  if (sent !== null) return <CriteriaStatus version={sent.version} liveVersion={currentVersion} sentAt={sent.sentAt} waiting />;

  return (
    <main className={styles.card}>
      <h2 className={styles.heading}>Send for second approval</h2>
      <p className={styles.lede}>A change to criteria needs a second person to approve it. You cannot approve your own change.</p>
      {changes.length > 0 ? (
        <ul className={styles.changes} aria-label="What changes">
          {changes.map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      ) : null}

      <div className={styles.field}>
        <label htmlFor={`${ids}-reason`} className={styles.label}>
          Why are you changing this?
        </label>
        <textarea
          id={`${ids}-reason`}
          className={styles.reason}
          maxLength={REASON_MAX_LENGTH}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-describedby={`${ids}-hint`}
          aria-invalid={errors.reason !== undefined}
        />
        <p id={`${ids}-hint`} className={styles.hint}>{`No patient information. Up to ${REASON_MAX_LENGTH} characters.`}</p>
        {errors.reason !== undefined ? <p role="alert" className={styles.error}>{errors.reason}</p> : null}
      </div>

      <fieldset className={styles.fieldset}>
        <legend className={styles.label}>Review again in</legend>
        <div className={styles.options}>
          {REVIEW_PERIODS.map((period) => (
            <OptionButton key={period} selected={months === period} onSelect={() => setMonths(period)} dataEl={`OWN-CRIT-SEND-REVIEW-${period}`}>
              {`${period} months`}
            </OptionButton>
          ))}
        </div>
        {errors.months !== undefined ? <p role="alert" className={styles.error}>{errors.months}</p> : null}
      </fieldset>

      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}

      <div className={styles.actions}>
        <Button variant="primary" busy={busy} onClick={send} dataEl="OWN-CRIT-SEND-BTN">
          Send for second approval
        </Button>
      </div>
    </main>
  );
}
