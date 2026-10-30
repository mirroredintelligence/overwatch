import type { Metadata } from 'next';
import { SupportCode } from '@/components/help/SupportCode';

export const metadata: Metadata = { title: 'Your support code - DIUCS capacity', robots: { index: false } };

// The person's own support code (W56). The page is the person's; it names nothing else.
export default function SharePage() {
  return (
    <main>
      <SupportCode />
    </main>
  );
}
