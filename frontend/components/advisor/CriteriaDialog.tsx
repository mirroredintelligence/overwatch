'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { bffFetch } from '@/lib/advisor/browser';
import type { CriteriaView } from '@/lib/advisor/criteria';
import styles from './dialog-body.module.css';

// The criteria of one service, in full (W14). Read only: a network service's criteria open the same
// way, with no change offered. "Report a problem" goes to the help page with the service named.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-09-12" as "12 Sep": the short form the criteria screen uses. */
export function shortDate(iso: string | null): string | null {
  if (iso === null) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (match === null) return null;
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]}`;
}

type Load = { kind: 'loading' } | { kind: 'ready'; view: CriteriaView } | { kind: 'failed' };

export function CriteriaDialog({
  serviceId,
  serviceName,
  onClose,
}: {
  serviceId: string;
  serviceName: string;
  onClose: () => void;
}) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let live = true;
    bffFetch<CriteriaView>(`/api/bff/services/${encodeURIComponent(serviceId)}/criteria`).then((reply) => {
      if (live) setLoad(reply.ok ? { kind: 'ready', view: reply.body } : { kind: 'failed' });
    });
    return () => {
      live = false;
    };
  }, [serviceId]);

  return (
    <Dialog title={`Criteria: ${serviceName}`} sub="Full view" dataEl="ADV-CRIT-DIALOG" onClose={onClose}>
      {load.kind === 'loading' ? <p className={styles.text}>Loading the criteria.</p> : null}
      {load.kind === 'failed' ? <p className={styles.error}>The criteria could not be read.</p> : null}
      {load.kind === 'ready' ? <Ready view={load.view} serviceId={serviceId} onClose={onClose} /> : null}
      {load.kind === 'failed' ? (
        <div className={styles.actions}>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      ) : null}
    </Dialog>
  );
}

function Ready({ view, serviceId, onClose }: { view: CriteriaView; serviceId: string; onClose: () => void }) {
  const reviewed = shortDate(view.reviewedOn);
  const reviewBy = shortDate(view.reviewBy) ?? view.reviewBy;
  const meta = `Version ${view.version} · reviewed ${reviewed ?? 'not recorded'} · review by ${reviewBy} · owner: ${view.owner ?? 'not recorded'}`;
  return (
    <div className={styles.body}>
      {view.overdue ? (
        <Banner
          tone="warning"
          title={reviewed === null ? 'Criteria are past their review date.' : `Criteria not reviewed since ${reviewed}`}
        />
      ) : null}
      <section>
        <h3 className={styles.heading}>Accepts</h3>
        <p className={styles.text}>{view.accepts ?? 'Not shown in this view. Phone the service to check.'}</p>
      </section>
      <section>
        <h3 className={styles.heading}>Does not accept</h3>
        <p className={styles.text}>{view.excludes ?? 'Not shown in this view. Phone the service to check.'}</p>
      </section>
      <p className={styles.meta}>{meta}</p>
      <div className={styles.actions}>
        <Button variant="neutral" href={`/help?topic=criteria&service=${encodeURIComponent(serviceId)}`}>
          Report a problem with these criteria
        </Button>
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}
