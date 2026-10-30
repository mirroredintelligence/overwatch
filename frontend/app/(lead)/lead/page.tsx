import type { Metadata } from 'next';
import { LeadOverview } from '@/components/lead/LeadOverview';

// The shift lead's main page (W17). At /lead: the route group (lead) is not part of the URL, so the
// page's own folder gives the path. The proxy keeps it to the lead role.

export const metadata: Metadata = {
  title: 'Shift lead - DIUCS capacity',
  robots: { index: false },
};

export default function ShiftLeadPage() {
  return <LeadOverview />;
}
