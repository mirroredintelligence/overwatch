import type { Metadata } from 'next';
import { NewSupportRequest } from '@/components/operator/NewSupportRequest';
import { SupportRequestList } from '@/components/operator/SupportRequestList';
import { TENANT_ID_PATTERN } from '@/lib/operator/words';

export const metadata: Metadata = { title: 'Ask for access - platform console', robots: { index: false } };

// Asking to look into an organisation (TEN-083), at /operator/support/new: the sheet over the requests. `for` names
// the organisation the person came from, and counts only when it is the shape of a tenant id (the form still
// offers live organisations only).
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { for: wanted } = await searchParams;
  const initial = typeof wanted === 'string' && TENANT_ID_PATTERN.test(wanted) ? wanted : undefined;
  return <SupportRequestList sheet={<NewSupportRequest initialTenant={initial} />} />;
}
