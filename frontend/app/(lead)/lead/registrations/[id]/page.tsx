import type { Metadata } from 'next';
import { CallBackCheck } from '@/components/lead/registration/CallBackCheck';
import { DecideStep } from '@/components/lead/registration/DecideStep';
import { GoLive } from '@/components/lead/registration/GoLive';
import { RegistrationStage } from '@/components/lead/registration/RegistrationStage';
import { ScopeCheck } from '@/components/lead/registration/ScopeCheck';
import { RegistrationOverview } from '@/components/lead/RegistrationOverview';

export const metadata: Metadata = {
  title: 'Registration review · Overwatch',
};

export const dynamic = 'force-dynamic';

// The review of one registration (W28, W29). The overview is the page; `?step=` opens one check beside the queue.
// The step is chosen from a fixed list, so an unknown value shows the overview, never a step. The stage number is
// the one RegistrationStage maps to its columns: 1 overview, 2 call back, 3 scope, 4 decide, 5 go live.
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
      return (
        <RegistrationStage stage={2} selectedId={id}>
          <CallBackCheck id={id} />
        </RegistrationStage>
      );
    case 'scope':
      return (
        <RegistrationStage stage={3} selectedId={id}>
          <ScopeCheck id={id} />
        </RegistrationStage>
      );
    case 'decide':
      return (
        <RegistrationStage stage={4} selectedId={id}>
          <DecideStep id={id} />
        </RegistrationStage>
      );
    case 'live':
      return (
        <RegistrationStage stage={5} selectedId={id}>
          <GoLive id={id} />
        </RegistrationStage>
      );
    default:
      return (
        <RegistrationStage stage={1} selectedId={id}>
          <RegistrationOverview id={id} />
        </RegistrationStage>
      );
  }
}
