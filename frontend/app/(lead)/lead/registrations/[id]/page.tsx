import type { Metadata } from 'next';
import { RegistrationOverview } from '@/components/lead/RegistrationOverview';

export const metadata: Metadata = {
  title: 'Registration review · DIUCS capacity',
};

export const dynamic = 'force-dynamic';

// The review of one registration. The overview is the top of the page; the check steps (W29) are
// reached from it by `?step=`.
export default async function RegistrationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RegistrationOverview id={id} />;
}
