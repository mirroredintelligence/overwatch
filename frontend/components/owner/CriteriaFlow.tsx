'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { parseCriteriaOverview, acceptsLine, doesNotAcceptLine, valuesOf } from '@/lib/criteria/model';
import { diffCriteria } from '@/lib/criteria/diff';
import type { CriteriaStep, CriteriaValues } from '@/lib/criteria/types';
import { useRead } from '@/lib/bff/useRead';
import styles from '@/components/lead/lead.module.css';
import { CriteriaConfirm } from './CriteriaConfirm';
import { CriteriaEditor } from './CriteriaEditor';
import { CriteriaOverview } from './CriteriaOverview';
import { CriteriaPreview } from './CriteriaPreview';
import { CriteriaSend } from './CriteriaSend';

// The owner's flow for one service (W30): the overview, then one step at a time. The steps after the
// overview need the current version, so they read it here; the overview reads it itself.

export function CriteriaFlow({ serviceId, initialStep }: { serviceId: string; initialStep: CriteriaStep }) {
  const [step, setStep] = useState<CriteriaStep>(initialStep);
  const [draft, setDraft] = useState<CriteriaValues | null>(null);

  if (step === 'overview') return <CriteriaOverview serviceId={serviceId} onNext={setStep} />;
  return <CriteriaSteps serviceId={serviceId} step={step} draft={draft} onStep={setStep} onDraft={setDraft} />;
}

function CriteriaSteps({
  serviceId,
  step,
  draft,
  onStep,
  onDraft,
}: {
  serviceId: string;
  step: CriteriaStep;
  draft: CriteriaValues | null;
  onStep: (next: CriteriaStep) => void;
  onDraft: (values: CriteriaValues) => void;
}) {
  const read = useRead(`/api/bff/criteria/${encodeURIComponent(serviceId)}`, parseCriteriaOverview);
  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="These criteria could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;

  const current = valuesOf(read.data.current);
  const version = read.data.current.version;
  // A step that needs a draft goes back to the editor when there is none (a deep link, or a reload).
  const needsDraft = step === 'preview' || step === 'send';
  if (needsDraft && draft === null) return <CriteriaEditor initial={current} onPreview={(values) => { onDraft(values); onStep('preview'); }} onCancel={() => onStep('overview')} />;

  switch (step) {
    case 'confirm':
      return <CriteriaConfirm serviceId={serviceId} version={version} onDone={() => onStep('overview')} onBack={() => onStep('overview')} />;
    case 'edit':
      return (
        <CriteriaEditor
          initial={current}
          onPreview={(values) => {
            onDraft(values);
            onStep('preview');
          }}
          onCancel={() => onStep('overview')}
        />
      );
    case 'preview': {
      const values = draft as CriteriaValues;
      return (
        <main className={styles.page}>
          <CriteriaPreview serviceName={read.data.serviceName} values={values} changes={diffCriteria(current, values)} />
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => onStep('send')} dataEl="OWN-CRIT-PREVIEW-CONTINUE-BTN">
              Continue
            </Button>
            <Button variant="neutral" onClick={() => onStep('edit')}>
              Back
            </Button>
          </div>
          <p className={styles.meta}>{acceptsLine(values)}</p>
          <p className={styles.meta}>{doesNotAcceptLine(values)}</p>
        </main>
      );
    }
    case 'send': {
      const values = draft as CriteriaValues;
      return (
        <CriteriaSend serviceId={serviceId} currentVersion={version} changes={diffCriteria(current, values)} values={values} />
      );
    }
    case 'overview':
      return null;
  }
}
