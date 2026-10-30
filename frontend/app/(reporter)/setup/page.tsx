import { SetupFlow, type SetupStep } from '@/components/reporter/setup/SetupFlow';

// The reporter's set-up (W33, W34): one page, the step in ?step= (welcome when absent). The
// invitation token is read from ?invite= and sent only to the BFF.

export const dynamic = 'force-dynamic';

const STEPS: readonly SetupStep[] = ['welcome', 'number', 'code', 'channel'];
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

export default async function SetupPage({
  searchParams,
}: {
  searchParams: Promise<{ step?: string; invite?: string }>;
}) {
  const { step, invite } = await searchParams;
  const chosen = STEPS.find((s) => s === step) ?? 'welcome';
  const token = invite !== undefined && TOKEN_SHAPE.test(invite) ? invite : '';
  return <SetupFlow step={chosen} invite={token} />;
}
