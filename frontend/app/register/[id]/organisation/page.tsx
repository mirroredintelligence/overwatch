import type { Metadata } from 'next';
import { OrganisationForm } from '@/components/register/OrganisationForm';

// Registration step 1, the organisation (Reg board). The form is the register frame and loads the invitation
// through the BFF.

export const metadata: Metadata = {
  title: 'Your organisation - Overwatch',
  robots: { index: false },
};

export default async function OrganisationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <OrganisationForm registrationId={id} />;
}
