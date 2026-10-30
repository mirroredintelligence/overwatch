import type { Metadata } from 'next';
import { Tour, type TourStep } from '@/components/tour/Tour';

export const metadata: Metadata = {
  title: 'DIUCS capacity: product tour',
};

const STEPS: readonly TourStep[] = ['welcome', 'role', 'changes', 'how', 'practice', 'week'];

// The tour is public: it holds no person's data, and it says nothing that depends on a session.
export default async function TourPage({ searchParams }: { searchParams: Promise<{ step?: string }> }) {
  const requested = (await searchParams).step ?? '';
  const step: TourStep = (STEPS as readonly string[]).includes(requested) ? (requested as TourStep) : 'welcome';
  return <Tour initialStep={step} />;
}
