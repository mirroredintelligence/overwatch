'use client';

// Red stub (DEC-010). W14 owns the phoned dialog; W17 needs only this seam.
export type PhonedDialogProps = { open: boolean; serviceName: string; onClose: () => void };
export function PhonedDialog(props: PhonedDialogProps) {
  void props;
  return null;
}
