import type { Metadata } from 'next';
import { AnalyticsOverview } from '@/components/analytics/AnalyticsOverview';

export const metadata: Metadata = {
  title: 'Analytics · Overwatch',
};

// The Analytics User's overview (DEC-1368). The proxy guard (lib/auth/access.ts) limits `/analytics` to the role
// `analytics-user`. The page reads figures through the BFF only: never a case, a patient, a postcode, an outcome or
// any personal data, and no total of places available.
export default function AnalyticsPage() {
  return (
    <main>
      <h1>Capacity overview</h1>
      <AnalyticsOverview />
    </main>
  );
}
