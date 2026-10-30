'use client';

import { useRouter } from 'next/navigation';
import type { OptionView } from '@/lib/advisor/options';
import { BookingPanel } from './BookingPanel';

// The booking control of one service on the options list and the map (W13, W20, W50): the panel for this
// case and this service, with the live stream opened once a booking exists, and the card's next steps
// wired to the finish screen. A network service never gets one (network-ui.md section 9): the caller
// does not mount this for it.

const STREAM_URL = '/api/bff/events';

function openStream() {
  return typeof EventSource === 'undefined' ? null : new EventSource(STREAM_URL);
}

export type OptionBookingProps = {
  caseId: string;
  option: Pick<OptionView, 'serviceId' | 'name' | 'phone'>;
  /** Back to the options: after a cancel, a decline, an expiry, or "See options again". */
  onSeeOptions?: () => void;
  onAskClinical?: () => void;
};

export function OptionBooking({ caseId, option, onSeeOptions, onAskClinical }: OptionBookingProps) {
  const router = useRouter();
  const finish = `/advisor/case/${encodeURIComponent(caseId)}/finish`;
  return (
    <BookingPanel
      caseRef={caseId}
      serviceId={option.serviceId}
      serviceName={option.name}
      servicePhone={option.phone}
      openStream={openStream}
      onSeeOptions={onSeeOptions}
      onAskClinical={onAskClinical}
      onRecordOutcome={() => router.push(finish)}
      onCopySummary={() => router.push(`${finish}#summary`)}
    />
  );
}
