import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Analytics · Overwatch',
};

// The Analytics User's landing page (DEC-1362): a placeholder until the district overview is built. The proxy guard
// (lib/auth/access.ts) limits `/analytics` to the role `analytics-user`. The page reads nothing: the role is an
// aggregate, read-only view and never reaches a case, a patient, a postcode, an outcome or any personal data.
export default function AnalyticsPage() {
  return (
    <main>
      <h1>Analytics</h1>
      <p>The overview of districts and services for commissioners and system leads is coming. It will show figures only.</p>
    </main>
  );
}
