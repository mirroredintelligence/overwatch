import type { Metadata } from 'next';
import { RegistrationStage } from '@/components/lead/registration/RegistrationStage';

export const metadata: Metadata = {
  title: 'Registrations · Overwatch',
};

export const dynamic = 'force-dynamic';

export default function RegistrationsPage() {
  return <RegistrationStage stage={0} />;
}
