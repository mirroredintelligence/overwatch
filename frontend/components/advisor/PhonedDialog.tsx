'use client';

import { useId } from 'react';
import { Button } from '@/components/ui/Button';

// SEAM for W17 (DEC-659). W14 owns the phoned dialog: the form, its focus trap and its return of focus.
// This is only the shell that W17's "Enter what they told me by phone" opens, so the page can be built
// and tested before W14 lands. W14 replaces this file's body and keeps these props.

export type PhonedDialogProps = {
  open: boolean;
  serviceName: string;
  onClose: () => void;
};

export function PhonedDialog({ open, serviceName, onClose }: PhonedDialogProps) {
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
