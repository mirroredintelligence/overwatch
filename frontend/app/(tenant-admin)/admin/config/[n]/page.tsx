import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { VersionDetail } from '@/components/admin/VersionDetail';

// One version of the settings (TEN-076). At /admin/config/<n>: a version number is a whole number; anything
// else is the page that is not there.

export const metadata: Metadata = {
  title: 'Settings version',
  robots: { index: false },
};

export default async function Page({ params }: { params: Promise<{ n: string }> }) {
  const { n } = await params;
  if (!/^[1-9][0-9]{0,5}$/.test(n)) notFound();
  return <VersionDetail version={Number(n)} />;
}
