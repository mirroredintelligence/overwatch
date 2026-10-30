'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { AdviceForm } from '@/components/clinical/AdviceForm';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { urgencyText, WHY_TEXT, type Urgency } from '@/lib/clinical/queue';
import styles from '@/components/exec/Exec.module.css';

// One taken request (W44, ClinicalAdvisor screens 5 to 7). The queue gives the urgency, the reason and
// the case number; the case's own details and what the advisor saw are not on the back end yet, so the
// screen says so rather than showing a guess. The advice form is kept (see the decisions).

export type CaseRequest = { id: string; urgency: Urgency; why: string; caseId: string };

const caseNumber = (caseId: string) => caseId.replace(/^case-/, '');

export function CaseView({ request }: { request: CaseRequest }) {
  const router = useRouter();
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const offDuty = async () => {
    setBusy(true);
    await bffRequest('/api/bff/clinical/presence', { method: 'PUT', body: { presence: 'away' } });
    setBusy(false);
    router.push('/clinical');
  };

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>{`Case ${caseNumber(request.caseId)}`}</h1>
      <section className={styles.section} aria-labelledby="case-the-case">
        <h2 id="case-the-case" className={styles.cardTitle}>The case</h2>
        <p>{`${urgencyText(request.urgency)} · ${WHY_TEXT[request.why] ?? request.why}`}</p>
        <p>The case details are not on this screen yet.</p>
      </section>
      <section className={styles.section} aria-labelledby="case-why">
        <h2 id="case-why" className={styles.cardTitle}>Why the advisor asked</h2>
        <p>{WHY_TEXT[request.why] ?? request.why}</p>
      </section>

      {sent ? (
        <section className={styles.section} aria-labelledby="advice-sent">
          <h2 id="advice-sent" className={styles.heading}>Advice sent</h2>
          <p>The advisor has it now. Logged for audit: your role, the time, your advice and what you saw.</p>
          <p className={styles.footer}>Clinical overrides are reviewed with the service leads, not used to assess advisors.</p>
          <div className={styles.actions}>
            <Link href="/clinical/requests" className={styles.backLink} data-el="CLIN-NEXT-BTN">Next request</Link>
            <Button variant="secondary" busy={busy} onClick={offDuty} dataEl="CLIN-OFFDUTY-BTN">Go off duty</Button>
          </div>
        </section>
      ) : (
        <section className={styles.section} aria-labelledby="advice-heading">
          <h2 id="advice-heading" className={styles.heading}>Give advice</h2>
          <AdviceForm requestId={request.id} onSent={() => setSent(true)} />
        </section>
      )}
    </div>
  );
}
