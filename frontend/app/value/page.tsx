import type { Metadata } from 'next';
import { ValueCase } from '@/components/value/ValueCase';

export const metadata: Metadata = {
  title: 'Overwatch: the value case',
  robots: { index: false },
};

// The value case is public, like the tour and the lessons: it holds no person's data and says nothing that
// depends on a session. It is a page to send to a sponsor, so it is not offered to search engines.
export default function ValuePage() {
  return <ValueCase />;
}
