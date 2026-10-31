import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { SupportTicketDetail } from '@/components/operator/SupportTicketDetail';
import { TICKET_ID_PATTERN } from '@/lib/operator/words';

export const metadata: Metadata = { title: 'Support request - platform console', robots: { index: false } };

// One request (TEN-083), at /operator/support/tickets/<id>. A malformed id is the page that is not there.
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!TICKET_ID_PATTERN.test(id)) notFound();
  return <SupportTicketDetail id={id} />;
}
