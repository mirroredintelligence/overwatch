import type { Metadata } from 'next';
import { FailedReplies } from '@/components/lead/FailedReplies';

// Replies we could not take in (DEC-1359). At /lead/replies.

export const metadata: Metadata = {
  title: 'Replies we could not take in - Overwatch',
  robots: { index: false },
};

export default function RepliesPage() {
  return <FailedReplies />;
}
