import type { Metadata } from 'next';
import { CallBackCheck } from '@/components/lead/registration/CallBackCheck';
import { DecideStep } from '@/components/lead/registration/DecideStep';
import { GoLive } from '@/components/lead/registration/GoLive';
import { ScopeCheck } from '@/components/lead/registration/ScopeCheck';
import { RegistrationOverview } from '@/components/lead/RegistrationOverview';

export const metadata: Metadata = {
  title: 'Registration review · DIUCS capacity',
};

export const dynamic = 'force-dynamic';

// The review of one registration (W28, W29). The overview is the page; `?step=` opens one check.
// The step is chosen from a fixed list, so an unknown value shows the overview, never a step.
export default async function RegistrationPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ step?: string | string[] }>;
}) {
  const { id } = await params;
  const { step } = await searchParams;
  switch (typeof step === 'string' ? step : undefined) {
    case 'callback':
      return <CallBackCheck id={id} />;
    case 'scope':
      return <ScopeCheck id={id} />;
    case 'decide':
      return <DecideStep id={id} />;
    case 'live':
      return <GoLive id={id} />;
    default:
      return <RegistrationOverview id={id} />;
  }
}
