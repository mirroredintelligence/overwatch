import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { RosterManager } from '@/components/lead/RosterManager';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// The duty roster of a service (DEC-1341). At /lead/services/<id>/roster. A malformed id is the same not-found as an
// unknown one.

export const metadata: Metadata = {
  title: 'Duty managers - Overwatch',
  robots: { index: false },
};

export default async function RosterPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!SERVICE_ID.test(id)) notFound();
  return <RosterManager serviceId={id} />;
}
