import type { Metadata } from 'next';
import { NewSupportRequest } from '@/components/operator/NewSupportRequest';
import { TENANT_ID_PATTERN } from '@/lib/operator/words';

export const metadata: Metadata = { title: 'Ask for access - platform console', robots: { index: false } };

// Asking to look into a tenant (TEN-083), at /operator/support/new. `for` names the tenant the person came
// from, and counts only when it is the shape of a tenant id (the form still offers active tenants only).
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { for: wanted } = await searchParams;
  const initial = typeof wanted === 'string' && TENANT_ID_PATTERN.test(wanted) ? wanted : undefined;
  return <NewSupportRequest initialTenant={initial} />;
}
