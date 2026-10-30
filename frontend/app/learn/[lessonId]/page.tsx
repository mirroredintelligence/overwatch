import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { LessonView } from '@/components/learn/LessonView';
import { HelpPanel } from '@/components/learn/HelpPanel';
import styles from '@/components/console/Console.module.css';
import { lessonById } from '@/lib/learn/content';

export const metadata: Metadata = {
  title: 'DIUCS capacity: lesson',
};

export default async function LessonPage({ params }: { params: Promise<{ lessonId: string }> }) {
  const { lessonId } = await params;
  if (lessonById(lessonId) === undefined) notFound();
  return (
    <div className={styles.page}>
      <LessonView lessonId={lessonId} />
      <HelpPanel spoaPhone={null} />
    </div>
  );
}
