import type { Metadata } from 'next';
import { ServiceForm } from '@/components/register/ServiceForm';

// Registration step 3, describing the service (Reg board). The form is the register frame and loads the
// invitation and the fixed-site answer through the BFF.

export const metadata: Metadata = {
  title: 'Describe the service - Overwatch',
  robots: { index: false },
};

export default async function ServicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ServiceForm registrationId={id} />;
}
