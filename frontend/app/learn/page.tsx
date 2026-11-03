import type { Metadata } from 'next';
import { HelpPanel } from '@/components/learn/HelpPanel';
import { LearnLibrary } from '@/components/learn/LearnLibrary';

export const metadata: Metadata = {
  title: 'Overwatch: lessons',
};

// The library holds no person's data, so it is public and needs no session.
export default function LearnPage() {
  return <LearnLibrary footer={<HelpPanel spoaPhone={null} />} />;
}
