import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { TenantDetail } from '@/components/operator/TenantDetail';
import { TENANT_ID_PATTERN } from '@/lib/operator/words';

export const metadata: Metadata = { title: 'Tenant - platform console', robots: { index: false } };

// One tenant (TEN-083), at /operator/tenants/<id>. An id that is not the shape of a tenant id is the page
// that is not there.
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!TENANT_ID_PATTERN.test(id) || id.startsWith('net-')) notFound();
  return <TenantDetail tenantId={id} />;
}
