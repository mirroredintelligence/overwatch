import { RespondScreen } from '@/components/reporter/app/RespondScreen';

export const dynamic = 'force-dynamic';

export default async function RespondPage({ params }: { params: Promise<{ serviceId: string }> }) {
  const { serviceId } = await params;
  return <RespondScreen serviceId={serviceId} />;
}
