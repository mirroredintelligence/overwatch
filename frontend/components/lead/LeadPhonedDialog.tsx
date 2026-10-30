'use client';

import { useId } from 'react';
import { Button } from '@/components/ui/Button';

// The lead's "Enter what they told me by phone" (W17, W42, W43). The advisor's phoned dialog (W14) records a
// service's answer for a case and needs a case reference; the lead's entry has none, and no back-end route
// takes a lead's phoned answer yet. So this is the shell only: it names the service and records nothing
// (DEC-659). The lead's route is a back-end gap.

export type LeadPhonedDialogProps = {
  open: boolean;
  serviceName: string;
  onClose: () => void;
};

export function LeadPhonedDialog({ open, serviceName, onClose }: LeadPhonedDialogProps) {
  const headingId = useId();
  if (!open) return null;
  return (
    <div role="dialog" aria-modal="true" aria-labelledby={headingId} data-el="PHONED-DIALOG">
      <h2 id={headingId}>Enter what they told me by phone</h2>
      <p>{serviceName}</p>
      <Button variant="neutral" dataEl="PHONED-CLOSE-BTN" onClick={onClose}>
        Close
      </Button>
    </div>
  );
}
