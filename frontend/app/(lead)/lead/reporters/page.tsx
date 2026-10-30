import type { Metadata } from 'next';
import { SetupTracker } from '@/components/lead/SetupTracker';

// Set-up progress for invited reporters (W43). At /lead/reporters.

export const metadata: Metadata = {
  title: 'Set-up progress - DIUCS capacity',
  robots: { index: false },
};

export default function ReportersPage() {
  return <SetupTracker />;
}
