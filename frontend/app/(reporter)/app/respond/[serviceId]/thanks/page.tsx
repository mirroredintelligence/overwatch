import { ThanksScreen } from '@/components/reporter/app/ThanksScreen';

export const dynamic = 'force-dynamic';

// The thanks page takes the recorded figure from its address (what was just recorded, not patient
// data). The list of today's reports is read from the BFF.
export default async function ThanksPage({
  params,
  searchParams,
}: {
  params: Promise<{ serviceId: string }>;
  searchParams: Promise<{ service?: string; unit?: string; value?: string; at?: string; next?: string }>;
}) {
  const { serviceId } = await params;
  const query = await searchParams;
  return (
    <ThanksScreen
      serviceId={serviceId}
      service={query.service ?? 'Your service'}
      unit={query.unit ?? 'referrals'}
      value={Number(query.value ?? 0)}
      at={query.at ?? ''}
      nextDue={query.next ?? ''}
    />
  );
}
