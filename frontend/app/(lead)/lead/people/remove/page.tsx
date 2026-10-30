import type { Metadata } from 'next';
import { RemovePersonForm } from '@/components/lead/RemovePersonForm';

// Remove a person's access (W42). At /lead/people/remove.

export const metadata: Metadata = {
  title: 'Remove access - DIUCS capacity',
  robots: { index: false },
};

export default function RemovePersonPage() {
  return <RemovePersonForm />;
}
