'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import type { DeclineReason } from '@/lib/advisor/service-api';
import styles from './dialog-body.module.css';

// "They declined" (W14): why a service that showed capacity said no. For a conversation with the
// service; it is not used to assess an advisor.

const REASONS: readonly { reason: DeclineReason; label: string; id: string }[] = [
  { reason: 'full', label: 'Full, not yet reported', id: 'FULL' },
  { reason: 'outside-criteria', label: 'Outside their criteria', id: 'OUTSIDE-CRITERIA' },
  { reason: 'staffing-or-transport', label: 'Staffing or transport', id: 'STAFFING' },
  { reason: 'other', label: 'Other', id: 'OTHER' },
];

const SAVE_FAILED = 'The reason could not be saved. Try again.';

export type DeclinedDialogProps = {
  caseRef: string;
  serviceId: string;
  serviceName: string;
  onSaved: () => void;
  onClose: () => void;
};

export function DeclinedDialog({ caseRef, serviceId, serviceName, onSaved, onClose }: DeclinedDialogProps) {
  const [reason, setReason] = useState<DeclineReason | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function save() {
    if (reason === null || busy) return;
    setBusy(true);
    setFailed(false);
    const reply = await bffFetch<{ recorded: boolean }>(
      `/api/bff/services/${encodeURIComponent(serviceId)}/declined`,
      { method: 'POST', body: { caseRef, reason }, idempotencyKey: newIdempotencyKey() },
    );
    if (reply.ok) {
      onSaved();
      onClose();
      return;
    }
    setBusy(false);
    setFailed(true);
  }

  return (
    <Dialog title="They declined" sub="The board showed capacity" dataEl="ADV-DECLINED-DIALOG" onClose={onClose}>
      <fieldset className={styles.group}>
        <legend className={styles.legend}>{`Why did ${serviceName} decline?`}</legend>
        {REASONS.map((item) => (
          <OptionButton
            key={item.reason}
            selected={reason === item.reason}
            onSelect={() => setReason(item.reason)}
            dataEl={`ADV-DECLINED-${item.id}`}
          >
            {item.label}
          </OptionButton>
        ))}
      </fieldset>

      <p className={styles.note}>For a conversation with the service. Not used to assess advisors.</p>
      {failed ? (
        <p role="alert" className={styles.error}>
          {SAVE_FAILED}
        </p>
      ) : null}

      <div className={styles.actions}>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" busy={busy} disabled={reason === null} dataEl="ADV-DECLINED-SAVE-BTN" onClick={save}>
          Save
        </Button>
      </div>
    </Dialog>
  );
}
