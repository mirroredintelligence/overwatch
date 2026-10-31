import type { ReactNode } from 'react';
import { OpenBookingAlerts } from '@/components/advisor/OpenBookingAlerts';

// Every advisor page carries the strip of open booking alerts above its own content (H-496): an
// unanswered withdrawal is seen by an advisor wherever they are, not only on the booking card.
export default function AdvisorLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <OpenBookingAlerts />
      {children}
    </>
  );
}
