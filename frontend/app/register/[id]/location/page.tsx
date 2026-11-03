import type { Metadata } from 'next';
import { LocationForm } from '@/components/register/LocationForm';

// Registration step 2, where the service is (Reg board). The form is the register frame and does the lookup
// through the BFF.

export const metadata: Metadata = {
  title: 'Where is the service? - Overwatch',
  robots: { index: false },
};

export default async function LocationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <LocationForm registrationId={id} />;
}
