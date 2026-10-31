import type { Metadata } from 'next';
import { CreateTenantForm } from '@/components/operator/CreateTenantForm';

export const metadata: Metadata = { title: 'Create a tenant - platform console', robots: { index: false } };

// Creating a tenant (TEN-083), at /operator/tenants/new: the operator's.
export default function Page() {
  return <CreateTenantForm />;
}
