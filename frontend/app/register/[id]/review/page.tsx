import type { Metadata } from 'next';
import { ReviewList } from '@/components/register/ReviewList';

// Registration step 5, the review (Reg board). The sections are read through the BFF; the list is the register frame.

export const metadata: Metadata = {
  title: 'Check your details - Overwatch',
  robots: { index: false },
};

export default async function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReviewList registrationId={id} />;
}
