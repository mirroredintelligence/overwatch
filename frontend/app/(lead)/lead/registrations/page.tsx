import type { Metadata } from 'next';
import { RegistrationQueue } from '@/components/lead/RegistrationQueue';

export const metadata: Metadata = {
  title: 'Registrations · Overwatch',
};

export const dynamic = 'force-dynamic';

export default function RegistrationsPage() {
  return <RegistrationQueue />;
}
