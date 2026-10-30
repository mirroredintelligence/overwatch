import type { Metadata } from 'next';
import { SafetyConcernForm } from '@/components/help/SafetyConcernForm';

export const metadata: Metadata = { title: 'Report a safety concern - DIUCS capacity' };

export default function SafetyConcernPage() {
  return (
    <main>
      <h1>Report a safety concern</h1>
      <SafetyConcernForm />
    </main>
  );
}
