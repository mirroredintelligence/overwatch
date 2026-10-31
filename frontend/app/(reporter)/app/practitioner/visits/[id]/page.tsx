import { VisitLoader } from '@/components/practitioner/VisitScreens';

// An accepted visit (RadarPhone 3): the address and contact, and the status list.
export const dynamic = 'force-dynamic';

export default async function VisitPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <VisitLoader id={id} />;
}
