import type { Metadata } from 'next';
import { InviteForm } from '@/components/lead/InviteForm';
import { ReporterStage } from '@/components/lead/ReporterStage';
import stageStyles from '@/components/lead/ReporterStage.module.css';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// Invite a reporter (W43; INV-02). At /lead/reporters/invite, with ?service=<id> to prefill the service. It is the
// compose state of the reporters page: the stage holds the form and the text preview.

export const metadata: Metadata = {
  title: 'Invite a reporter - Overwatch',
  robots: { index: false },
};

export default async function InvitePage({ searchParams }: { searchParams: Promise<{ service?: string | string[] }> }) {
  const { service } = await searchParams;
  const list = (
    <div className={stageStyles.card}>
      <h2 className={stageStyles.cardHeading}>Set-up progress</h2>
      <p className={stageStyles.cardText}>Everyone you have invited, and where each one has got to.</p>
      <Button variant="secondary" href="/lead/reporters" dataEl="LEAD-INVITE-PROGRESS-BTN">
        See set-up progress
      </Button>
    </div>
  );
  return (
    <main className={stageStyles.page}>
      <PageHeader title="Reporters" />
      <ReporterStage
        state="compose"
        list={list}
        compose={<InviteForm serviceId={typeof service === 'string' && SERVICE_ID.test(service) ? service : undefined} />}
      />
    </main>
  );
}
