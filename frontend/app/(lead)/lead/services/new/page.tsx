import type { Metadata } from 'next';
import { Suspense } from 'react';
import { AddServiceForm } from '@/components/lead/AddServiceForm';

// Add a service reporter (W18, LDR-03 and LDR-04: four steps, then the added state). At /lead/services/new; the
// step is in ?step=, which the form reads on the client, so the form sits in a Suspense boundary.

export const metadata: Metadata = {
  title: 'Add a service reporter - Overwatch',
  robots: { index: false },
};

export default function AddServicePage() {
  return (
    <Suspense fallback={null}>
      <AddServiceForm />
    </Suspense>
  );
}
