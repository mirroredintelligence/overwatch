'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { shortDate } from '@/lib/criteria/model';
import styles from '@/components/lead/lead.module.css';

// The owner's notice that the review date has passed (W31, ui-screens CriteriaOwner screen 8). The
// owner can review now, or ask for the owner to be changed: that only shows the shift lead's role and
// phone as text. No message is sent from here.

export function OverdueNotice({
  serviceName,
  overdueSince,
  shiftLead,
  onReview,
}: {
  serviceName: string;
  overdueSince: string;
  shiftLead?: { role: string; phone: string };
  onReview?: () => void;
}) {
  const [asked, setAsked] = useState(false);
  return (
    <section className={styles.card} aria-labelledby="overdue-heading">
      <h2 id="overdue-heading" className={styles.section}>{`Criteria not reviewed since ${shortDate(overdueSince)}`}</h2>
      <p>{`Advisors see a flag on ${serviceName}: “criteria not reviewed”.`}</p>
      <p>Not your service any more? Ask the shift lead to change the owner.</p>
      <div className={styles.actions}>
        <Button variant="primary" onClick={() => onReview?.()} dataEl="OWN-OVERDUE-REVIEW-BTN">
          Review now
        </Button>
        <Button variant="secondary" onClick={() => setAsked(true)} dataEl="OWN-OVERDUE-ASK-BTN">
          Ask to change the owner
        </Button>
      </div>
      {asked ? (
        <p aria-live="polite">
          {shiftLead !== undefined
            ? `Shift lead: ${shiftLead.role}, ${shiftLead.phone}. No message is sent.`
            : 'Ask the shift lead to change the owner. No message is sent.'}
        </p>
      ) : null}
    </section>
  );
}
