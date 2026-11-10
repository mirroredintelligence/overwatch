import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Advisor v2 · Overwatch',
};

// The landing page of the new advisor pages (DEC-1362): a placeholder until the finder (postcode, age, need,
// urgency, group cards, services) is built. The proxy guard (lib/auth/access.ts) opens `/advisor/v2` to the
// advisor and to Advisor v2. It sits in its own route group so it does not carry the v1 booking-alert strip,
// whose reads Advisor v2 does not hold.
export default function AdvisorV2Page() {
  return (
    <main>
      <h1>Advisor v2</h1>
      <p>The new advisor finder is coming.</p>
    </main>
  );
}
