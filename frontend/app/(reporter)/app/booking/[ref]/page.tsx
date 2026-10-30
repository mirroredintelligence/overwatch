import { BookingDecision } from '@/components/reporter/app/BookingDecision';

export const dynamic = 'force-dynamic';

export default async function BookingPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <BookingDecision reference={ref} />;
}
