'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { leadRead } from '@/lib/lead/browser';
import { listOf, textOf } from '@/lib/lead/answers';
import { SETUP_STEPS, type SetupSteps } from '@/lib/lead/setupProgress';
import { ReporterDetail } from './ReporterDetail';
import { ReporterList } from './ReporterList';
import { ReporterStage } from './ReporterStage';
import stageStyles from './ReporterStage.module.css';

// Set-up progress for each invitation (W43; INV-01): the list of invitations, and beside it one reporter's
// set-up. The open reporter is in the address, /lead/reporters?invitation=<id>, so Back and a reload work. The
// list is ReporterList, the open reporter is ReporterDetail, and ReporterStage lays them out.

export type Invitation = {
  id: string;
  serviceId: string;
  serviceName: string;
  role: string;
  inviteeName?: string | null;
  steps: SetupSteps;
  invitedAt: string;
  lastSeen: string;
  firstReportAt: string | null;
};

const REPORTERS = '/lead/reporters';

function invitationsFrom(body: unknown): Invitation[] {
  return listOf(body, 'items').map((item) => {
    const row = item as Record<string, unknown>;
    const steps = row.steps as Record<string, unknown>;
    const flags = {} as SetupSteps;
    for (const step of SETUP_STEPS) {
      if (typeof steps?.[step] !== 'boolean') throw new Error('step');
      flags[step] = steps[step] as boolean;
    }
    return {
      id: textOf(row.id),
      serviceId: textOf(row.serviceId),
      serviceName: textOf(row.serviceName),
      role: textOf(row.role),
      inviteeName: typeof row.inviteeName === 'string' && row.inviteeName.trim() ? row.inviteeName : null,
      steps: flags,
      invitedAt: textOf(row.invitedAt),
      lastSeen: textOf(row.lastSeen),
      firstReportAt: typeof row.firstReportAt === 'string' ? row.firstReportAt : null,
    };
  });
}

export function SetupTracker() {
  const router = useRouter();
  const openId = useSearchParams().get('invitation');
  const [items, setItems] = useState<Invitation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [now] = useState(() => Date.now());
  const [notice, setNotice] = useState<{ text: string; failed: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void leadRead('/api/bff/lead/invitations').then((result) => {
      if (cancelled) return;
      try {
        if (!result.ok) throw new Error('refused');
        setItems(invitationsFrom(result.body));
      } catch {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function tryAgain() {
    setFailed(false);
    setItems(null);
    setAttempt((count) => count + 1);
  }

  const open = openId !== null ? (items?.find((item) => item.id === openId) ?? null) : null;

  let list;
  if (failed) {
    list = (
      <div className={stageStyles.card} role="alert" data-tone="error">
        <h2 className={stageStyles.cardHeading}>
          <span aria-hidden="true">▲ </span>We could not load set-up progress
        </h2>
        <p className={stageStyles.cardText}>
          Nothing has been lost. Check your connection and try again. If it keeps happening, tell the Overwatch team.
        </p>
        <Button variant="secondary" onClick={tryAgain} dataEl="LEAD-TRACK-RETRY-BTN">
          Try again
        </Button>
      </div>
    );
  } else if (items === null) {
    list = (
      <Loading label="Loading the set-up progress.">
        <SkeletonRows count={3} />
      </Loading>
    );
  } else if (items.length === 0) {
    list = (
      <div className={stageStyles.card}>
        <h2 className={stageStyles.cardHeading}>No one has been invited yet</h2>
        <p className={stageStyles.cardText}>
          Invite the first person who reports capacity for a service. They set up in about 3 minutes on their own phone.
        </p>
        <Button variant="primary" href="/lead/reporters/invite" dataEl="LEAD-TRACK-INVITE-FIRST-BTN">
          Invite someone
        </Button>
      </div>
    );
  } else {
    list = <ReporterList items={items} now={now} currentId={open?.id ?? null} onOpen={(id) => router.push(`${REPORTERS}?invitation=${encodeURIComponent(id)}`)} />;
  }

  let detail = null;
  if (open !== null) {
    detail = (
      <ReporterDetail
        key={open.id}
        item={open}
        now={now}
        onBack={() => router.push(REPORTERS)}
        onNotice={(text, isFailed) => setNotice({ text, failed: isFailed })}
      />
    );
  } else if (openId !== null && items !== null) {
    detail = (
      <div className={stageStyles.card}>
        <p className={stageStyles.cardText}>We could not find that invitation. Choose one from the list.</p>
        <Button variant="secondary" onClick={() => router.push(REPORTERS)} dataEl="LEAD-TRACK-BACK-BTN">
          Back to the list
        </Button>
      </div>
    );
  }

  return (
    <main className={stageStyles.page}>
      <PageHeader title="Reporters" />
      <p role={notice?.failed ? 'alert' : 'status'} className={stageStyles.notice} data-failed={notice?.failed ?? false}>
        {notice?.text ?? ''}
      </p>
      <ReporterStage state={openId !== null ? 'detail' : 'browse'} list={list} detail={detail} />
    </main>
  );
}
