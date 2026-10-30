import { LockedScreen } from '@/components/reporter/app/LockedScreen';

export const dynamic = 'force-dynamic';

export default async function LockedPage({ searchParams }: { searchParams: Promise<{ reason?: string }> }) {
  const { reason } = await searchParams;
  return <LockedScreen reason={reason ?? null} />;
}
