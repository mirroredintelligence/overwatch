import { VisitLoader } from '@/components/practitioner/VisitScreens';

// An accepted visit (RadarPhone 3, B11): the address and contact, the status radios and the closed words.
export const dynamic = 'force-dynamic';

export default async function VisitPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <VisitLoader id={id} />;
}
