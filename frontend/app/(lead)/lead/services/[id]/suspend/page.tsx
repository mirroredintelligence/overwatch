import type { Metadata } from 'next';
import { SuspendService } from '@/components/lead/SuspendService';

// Suspend or resume a service (W42). At /lead/services/<id>/suspend.

export const metadata: Metadata = {
  title: 'Suspend a service - DIUCS capacity',
  robots: { index: false },
};

export default async function SuspendPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SuspendService serviceId={id} />;
}
