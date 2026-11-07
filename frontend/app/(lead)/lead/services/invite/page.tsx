import type { Metadata } from 'next';
import { InviteServiceForm } from '@/components/lead/InviteServiceForm';

// Invite a service (DEC-1341 item 1a). At /lead/services/invite. The other way in is "Add a service" (/lead/services/new).

export const metadata: Metadata = {
  title: 'Invite a service - Overwatch',
  robots: { index: false },
};

export default function InviteServicePage() {
  return <InviteServiceForm />;
}
