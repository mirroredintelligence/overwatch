import type { Metadata } from 'next';
import { Suspense } from 'react';
import { SetupTracker } from '@/components/lead/SetupTracker';

// Set-up progress for invited reporters (W43; INV-01). At /lead/reporters, with ?invitation=<id> to open one.
// The tracker reads the address, so it sits in a Suspense boundary.

export const metadata: Metadata = {
  title: 'Reporters - Overwatch',
  robots: { index: false },
};

export default function ReportersPage() {
  return (
    <Suspense>
      <SetupTracker />
    </Suspense>
  );
}
