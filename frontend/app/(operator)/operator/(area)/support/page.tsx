import type { Metadata } from 'next';
import { SupportRequestList } from '@/components/operator/SupportRequestList';

export const metadata: Metadata = { title: 'Support requests - platform console', robots: { index: false } };

// A support person's requests (TEN-083), at /operator/support.
export default function Page() {
  return <SupportRequestList />;
}
