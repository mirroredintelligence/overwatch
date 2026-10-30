'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffPost } from '@/lib/bff/client';
import { REVIEW_PERIODS, reviewPeriodError } from '@/lib/criteria/model';
import type { ReviewPeriod } from '@/lib/criteria/types';
import styles from '@/components/lead/lead.module.css';

// "Still right" (W30, ui-screens CriteriaOwner screen 3): the owner confirms the current criteria are
// current and safe, and chooses when to review them again. Nothing changes but the review date.

export function CriteriaConfirm({
  serviceId,
  version,
  onDone,
  onBack,
}: {
  serviceId: string;
  version: number;
  onDone?: () => void;
  onBack?: () => void;
}) {
  const [months, setMonths] = useState<ReviewPeriod | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const confirm = async () => {
    const found = reviewPeriodError(months);
    setError(found);
    if (found !== null || months === null) return;
    setBusy(true);
    setFailure(null);
    const result = await bffPost(`/api/bff/criteria/${encodeURIComponent(serviceId)}/confirm`, { reviewInMonths: months });
    setBusy(false);
    if (result.ok) setDone(true);
    else setFailure('Your confirmation was not recorded. Try again.');
  };

  return (
    <main className={styles.page}>
      <p className={styles.meta}>{`Version ${version}`}</p>
      <h2 className={styles.heading}>Are these still right?</h2>
      <p className={styles.lede}>By confirming, you say the criteria are current and safe for advisors to rely on.</p>

      <fieldset className={styles.fieldset}>
        <legend>Review again in</legend>
        {REVIEW_PERIODS.map((period) => (
          <OptionButton
            key={period}
            selected={months === period}
            onSelect={() => setMonths(period)}
            dataEl={`OWN-CRIT-REVIEW-${period}`}
          >
            {`${period} months`}
          </OptionButton>
        ))}
        {error !== null ? <p role="alert" className={styles.error}>{error}</p> : null}
      </fieldset>

      <p className={styles.hint}>We log your confirmation, the date and your role.</p>
      {failure !== null ? <p role="alert" className={styles.error}>{failure}</p> : null}
      {done ? <p aria-live="polite">Confirmed.</p> : null}

      <div className={styles.actions}>
        <Button variant="primary" busy={busy} onClick={confirm} dataEl="OWN-CRIT-CONFIRM-BTN">
          I confirm
        </Button>
        {done ? (
          <Button variant="secondary" onClick={() => onDone?.()}>
            Back to the criteria
          </Button>
        ) : (
          <Button variant="neutral" onClick={() => onBack?.()}>
            Back
          </Button>
        )}
      </div>
    </main>
  );
}
