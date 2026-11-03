import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { LessonView } from '@/components/learn/LessonView';
import { HelpPanel } from '@/components/learn/HelpPanel';
import { LearnLibrary } from '@/components/learn/LearnLibrary';
import { lessonById } from '@/lib/learn/content';

export const metadata: Metadata = {
  title: 'Overwatch: lesson',
};

export default async function LessonPage({ params }: { params: Promise<{ lessonId: string }> }) {
  const { lessonId } = await params;
  const lesson = lessonById(lessonId);
  if (lesson === undefined) notFound();
  return (
    <LearnLibrary initialRole={lesson.role} activeId={lessonId} footer={<HelpPanel spoaPhone={null} />}>
      <LessonView lessonId={lessonId} />
    </LearnLibrary>
  );
}
