'use client';

import { useState, useSyncExternalStore, type ReactNode } from 'react';
import { MorphStage } from '@/components/morph/MorphStage';
import { StepBar, type Step } from '@/components/morph/StepBar';
import { SummaryPin, type SummaryItem } from '@/components/morph/SummaryPin';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { acceptsLine, doesNotAcceptLine, parseCriteriaOverview, shortDate, valuesOf } from '@/lib/criteria/model';
import { diffCriteria } from '@/lib/criteria/diff';
import type { CriteriaOverview as Overview, CriteriaStep, CriteriaValues } from '@/lib/criteria/types';
import { useRead, type ReadState } from '@/lib/bff/useRead';
import styles from '@/components/lead/lead-forms.module.css';
import flow from './CriteriaFlow.module.css';
import { CriteriaConfirm } from './CriteriaConfirm';
import { CriteriaEditor } from './CriteriaEditor';
import { CriteriaOverview } from './CriteriaOverview';
import { CriteriaPreview } from './CriteriaPreview';
import { CriteriaSend } from './CriteriaSend';

// The owner's flow for one service (W30, boards/lead/OwnerReview.dc.html). The five steps are stages of one
// MorphStage: the live criteria are pinned beside the stage (a line above it on a phone), and the steps are
// numbered in a StepBar. The board's sixth step, Waiting, is the tracker CriteriaSend shows once the change is
// sent, so it has no stage of its own. The steps after the overview need the current version, so they read it
// here; the overview reads it itself.

const STAGES: readonly CriteriaStep[] = ['overview', 'confirm', 'edit', 'preview', 'send'];
const STEPS: readonly Step[] = [{ label: 'Review' }, { label: 'Confirm' }, { label: 'Change' }, { label: 'Preview' }, { label: 'Send' }];
const HINTS = [
  'A review is due. Still right, or change.',
  'Confirming is one deliberate step, and it is logged.',
  'Changed fields say so, and what they were.',
  'The owner sees what advisors will see, and what changed.',
  'A second person must approve. Not you.',
];
// A step that needs a draft opens the change step when there is none (a deep link, or a reload).
const NEEDS_DRAFT: readonly CriteriaStep[] = ['preview', 'send'];
const PREVIEW = STAGES.indexOf('preview');
const SEND = STAGES.indexOf('send');
const NARROW = '(max-width: 700px)';
const WIDE_COLUMNS = ['330px minmax(0,1fr) 0px'];
const WIDE_GAPS = ['22px'];
const NARROW_COLUMNS = ['0px minmax(0,1fr) 0px'];
const NARROW_GAPS = ['0px'];

// The live criteria are a card beside the stage on a desktop, and a line above it on a phone.
function subscribeNarrow(onChange: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => undefined;
  const query = window.matchMedia(NARROW);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

function isNarrow(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(NARROW).matches;
}

function useNarrow(): boolean {
  return useSyncExternalStore(subscribeNarrow, isNarrow, () => false);
}

export function CriteriaFlow({ serviceId, initialStep }: { serviceId: string; initialStep: CriteriaStep }) {
  const read = useRead<Overview>(`/api/bff/criteria/${encodeURIComponent(serviceId)}`, parseCriteriaOverview);
  const narrow = useNarrow();
  const start = NEEDS_DRAFT.includes(initialStep) ? STAGES.indexOf('edit') : STAGES.indexOf(initialStep);
  const [stage, setStage] = useState(start);
  const [furthest, setFurthest] = useState(start);
  const [draft, setDraft] = useState<CriteriaValues | null>(null);

  const go = (next: number) => {
    setStage(next);
    setFurthest((reached) => Math.max(reached, next));
  };

  const ready = read.status === 'ok' ? read.data : null;
  const layers: (() => ReactNode)[] = [
    () => <CriteriaOverview serviceId={serviceId} onNext={(next) => go(STAGES.indexOf(next))} />,
    () =>
      ready === null ? (
        <Waiting read={read} />
      ) : (
        <CriteriaConfirm serviceId={serviceId} version={ready.current.version} onDone={() => go(0)} onBack={() => go(0)} />
      ),
    () =>
      ready === null ? (
        <Waiting read={read} />
      ) : (
        <CriteriaEditor
          initial={valuesOf(ready.current)}
          onPreview={(values) => {
            setDraft(values);
            go(PREVIEW);
          }}
          onCancel={() => go(0)}
        />
      ),
    () => {
      if (ready === null || draft === null) return <Waiting read={read} />;
      return (
        <div className={styles.page}>
          <CriteriaPreview serviceName={ready.serviceName} values={draft} changes={diffCriteria(valuesOf(ready.current), draft)} />
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => go(SEND)} dataEl="OWN-CRIT-PREVIEW-CONTINUE-BTN">
              Continue
            </Button>
            <Button variant="neutral" onClick={() => go(STAGES.indexOf('edit'))}>
              Back
            </Button>
          </div>
          <p className={styles.meta}>{acceptsLine(draft)}</p>
          <p className={styles.meta}>{doesNotAcceptLine(draft)}</p>
        </div>
      );
    },
    () =>
      ready === null || draft === null ? (
        <Waiting read={read} />
      ) : (
        <CriteriaSend serviceId={serviceId} currentVersion={ready.current.version} changes={diffCriteria(valuesOf(ready.current), draft)} values={draft} />
      ),
  ];

  return (
    <div className={flow.root}>
      <div className={flow.bar}>
        <StepBar label="Criteria steps" steps={STEPS} current={stage} reached={furthest} onSelect={go} />
        <p className={flow.hint}>{HINTS[stage]}</p>
      </div>
      {narrow ? <Pinned read={read} variant="pill" /> : null}
      <MorphStage
        label="Criteria step"
        current={stage}
        templates={narrow ? NARROW_COLUMNS : WIDE_COLUMNS}
        gaps={narrow ? NARROW_GAPS : WIDE_GAPS}
        layers={layers}
        summary={narrow ? undefined : <Pinned read={read} variant="card" />}
      />
    </div>
  );
}

/** The live version, its state as a shape and a word, and what advisors accept and refuse. */
function Pinned({ read, variant }: { read: ReadState<Overview>; variant: 'card' | 'pill' }) {
  if (read.status === 'loading') {
    return (
      <Loading label="Loading the criteria.">
        <Skeleton shape="block" />
      </Loading>
    );
  }
  if (read.status === 'failed') return <p className={flow.failed}>The live criteria could not be loaded.</p>;

  const { current, draft, overdueSince } = read.data;
  const values = valuesOf(current);
  const waiting = draft?.status === 'waiting';
  const chip: { variant: StatusTagVariant; text: string } = waiting
    ? { variant: 'waiting', text: 'Change waiting for approval' }
    : overdueSince !== undefined
      ? { variant: 'problem', text: `Live · review overdue since ${shortDate(overdueSince)}` }
      : { variant: 'live', text: `Live · review by ${shortDate(current.reviewBy)}` };
  const items: SummaryItem[] = [
    {
      key: 'version',
      label: 'Live version',
      value: `Version ${current.version}`,
      detail: waiting ? `Advisors still see version ${current.version}.` : 'Advisors see this version now.',
    },
    // The model's lines begin with their label ("Accepts: ..."); the pin shows the label as its heading.
    { key: 'accepts', label: 'Accepts', value: acceptsLine(values).replace(/^Accepts: /, '') },
    { key: 'excludes', label: 'Does not accept', value: doesNotAcceptLine(values).replace(/^Does not accept: /, '') },
  ];
  return (
    <div className={flow.pinned}>
      <StatusTag variant={chip.variant}>{chip.text}</StatusTag>
      <SummaryPin items={items} variant={variant} title="Live criteria" label="Live criteria" />
    </div>
  );
}

/** A step's stage while the criteria are read, or when they could not be. */
function Waiting({ read }: { read: ReadState<Overview> }) {
  if (read.status === 'failed') {
    return (
      <div className={styles.page}>
        <Banner tone="warning" title="These criteria could not be loaded. Try again shortly." />
      </div>
    );
  }
  return (
    <div className={styles.page}>
      <Loading label="Loading the criteria.">
        <Skeleton shape="block" />
      </Loading>
    </div>
  );
}
