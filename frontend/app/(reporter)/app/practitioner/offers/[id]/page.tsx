import { VisitLoader } from '@/components/practitioner/VisitScreens';

// A visit offer (RadarPhone 2, B11). The same resource as the accepted visit: the screen shows whichever stage
// it is at, so a link to either path is never wrong.
export const dynamic = 'force-dynamic';

export default async function OfferPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <VisitLoader id={id} />;
}
