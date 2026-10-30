import type { Metadata } from 'next';
import { AddServiceForm } from '@/components/lead/AddServiceForm';

// Add a service reporter (W18). At /lead/services/new.

export const metadata: Metadata = {
  title: 'Add a service reporter - DIUCS capacity',
  robots: { index: false },
};

export default function AddServicePage() {
  return <AddServiceForm />;
}
