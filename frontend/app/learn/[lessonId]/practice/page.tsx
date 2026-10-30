import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { PracticeView } from '@/components/learn/PracticeView';
import { lessonById } from '@/lib/learn/content';

export const metadata: Metadata = {
  title: 'DIUCS capacity: practice',
};

export default async function PracticePage({ params }: { params: Promise<{ lessonId: string }> }) {
  const { lessonId } = await params;
  if (lessonById(lessonId) === undefined) notFound();
  return <PracticeView lessonId={lessonId} />;
}
