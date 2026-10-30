import type { Metadata } from 'next';
import { ReportFlags } from '@/components/lead/ReportFlags';

// Reports to check (W42). At /lead/flags.

export const metadata: Metadata = {
  title: 'Reports to check - DIUCS capacity',
  robots: { index: false },
};

export default function FlagsPage() {
  return <ReportFlags />;
}
