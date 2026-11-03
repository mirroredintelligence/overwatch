import type { Metadata } from 'next';
import { ReportingForm } from '@/components/register/ReportingForm';

// Registration step 4, how the service reports capacity (Reg board). The form is the register frame.

export const metadata: Metadata = {
  title: 'How will you report capacity? - Overwatch',
  robots: { index: false },
};

export default async function ReportingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReportingForm registrationId={id} />;
}
