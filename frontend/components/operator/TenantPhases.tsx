'use client';

import { forwardRef, useId, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { PHASE_STATE_WORD, teamName, type ConsentRead, type Funnel, type FunnelPhase, type PhaseId, type StepId } from '@/lib/operator/funnel';
import { organisationTypeWord } from '@/lib/operator/words';
import { whenText } from '@/lib/tenantAdmin/words';
import { GoLiveStep, type Notice } from './TenantLifecycle';
import { AgreementsStep, InviteStep, OrganisationStep, ReachStep, RolesStep, SignInStep, TeamStep, type Detail, type PanelProps } from './TenantPanels';
import styles from '@/components/admin/admin.module.css';
import ts from './Tenant.module.css';

// The one selected part of the organisation's page. A part that is not completed shows its steps: the forms, one
// primary button. A completed part shows a short summary and a "Change" link, and its steps only once the operator
// asks (or has just done something in it, so what was said stays on screen).

const LEDE: Record<PhaseId, string> = {
  organisation: 'Check this is the right organisation, then connect the Microsoft work accounts its people sign in with.',
  approval: '',
  teams: 'What a person can do in Overwatch comes from the teams they are in. Start with the administrators’ team.',
  reach: 'Set the web address people use and the number their texts come from, and record the agreements that are in place (recommended, not required).',
  golive: 'Check what is left. When everything is ready you can make the organisation live.',
};

export const phaseTagClass = (state: FunnelPhase['state']): string =>
  state === 'completed' ? styles.tag : state === 'in-progress' ? `${styles.tag} ${ts.tagInProgress}` : state === 'waiting' ? `${styles.tag} ${ts.tagWaiting}` : `${styles.tag} ${styles.tagDashed}`;

type FactRow = readonly [string, ReactNode];

function facts(phase: PhaseId, detail: Detail, consent: ConsentRead, funnel: Funnel): FactRow[] {
  const t = detail.tenant;
  if (phase === 'organisation')
    return [
      ['Organisation', t.displayName],
      ['Type', organisationTypeWord(t.organisationType)],
      ['NHS code', t.odsCode ?? 'None'],
      ['Microsoft work accounts', 'Connected and confirmed'],
    ];
  if (phase === 'approval') {
    const invitation = consent.status === 'ok' ? consent.data.invitation : null;
    return [['Approved', invitation?.consentedAt ? whenText(invitation.consentedAt) : 'Yes']];
  }
  if (phase === 'teams') {
    const others = [...new Set(detail.roleMappings.filter((m) => m.status === 'active' && m.role !== 'tenant-admin').map((m) => teamName(m.role)))];
    return [
      ['Administrators’ team', 'Added'],
      ['Other teams', others.join(', ')],
    ];
  }
  if (phase === 'reach') {
    const tested = detail.numbers.filter((n) => n.status === 'active' && n.testedAt !== null).map((n) => n.e164);
    const shared = detail.sharedLine !== null && detail.sharedLine.status === 'active' && detail.sharedLine.testedAt !== null;
    const recorded = 3 - funnel.recommended;
    return [
      ['Web address', detail.host ?? 'Not set'],
      ['Text number', tested.length > 0 ? `${tested.join(', ')} (tested)` : shared ? 'Overwatch’s shared line, sending only (tested)' : 'Not tested'],
      ['Agreements (recommended)', recorded === 3 ? 'All three recorded' : `${recorded} of 3 recorded`],
    ];
  }
  return [];
}

type Props = {
  tenantId: string;
  detail: Detail;
  consent: ConsentRead;
  funnel: Funnel;
  phase: FunnelPhase;
  /** The completed part whose steps are shown (the operator asked to change it, or has just done something in it). */
  open: PhaseId | null;
  onOpen: (phase: PhaseId) => void;
  onSelect: (phase: PhaseId) => void;
  onChanged: () => void;
  onUnrecorded: () => void;
  onNotice: (notice: Notice) => void;
};

export const PhasePanel = forwardRef<HTMLHeadingElement, Props>(function PhasePanel(props, headingRef) {
  const { phase, funnel, detail, consent } = props;
  const headingId = useId();
  const showSteps = !phase.done || props.open === phase.id || phase.id === 'golive';
  const firstTodo = phase.steps.find((id) => !funnel.steps.find((s) => s.id === id)!.done);
  const step = (id: StepId) => funnel.steps.find((s) => s.id === id)!;
  const panel = (id: StepId): PanelProps => ({
    tenantId: props.tenantId,
    detail,
    consent,
    step: step(id),
    isNext: firstTodo === id,
    heading: phase.steps.length > 1,
    onChanged: props.onChanged,
    onUnrecorded: props.onUnrecorded,
  });
  const nextPhase = funnel.phases.find((p) => !p.done && p.id !== phase.id);
  const editable = phase.id !== 'approval';

  return (
    <section className={ts.panel} aria-labelledby={headingId} data-el={`OP-PHASE-${phase.id.toUpperCase()}`} data-state={phase.state}>
      <header className={ts.panelHead}>
        <p className={ts.eyebrow}>{`Part ${phase.number} of ${funnel.phases.length}`}</p>
        <h2 id={headingId} ref={headingRef} tabIndex={-1} className={ts.panelTitle}>
          {phase.title}
        </h2>
        <span className={phaseTagClass(phase.state)}>{PHASE_STATE_WORD[phase.state]}</span>
      </header>

      {showSteps ? (
        <>
          {LEDE[phase.id] !== '' ? <p className={ts.lede}>{LEDE[phase.id]}</p> : null}
          {phase.id === 'organisation' ? (
            <>
              <OrganisationStep {...panel('organisation')} />
              <SignInStep {...panel('signin')} />
            </>
          ) : null}
          {phase.id === 'approval' ? <InviteStep {...panel('invite')} /> : null}
          {phase.id === 'teams' ? (
            <>
              <TeamStep {...panel('team')} />
              <RolesStep {...panel('roles')} />
            </>
          ) : null}
          {phase.id === 'reach' ? (
            <>
              <ReachStep {...panel('reach')} />
              <AgreementsStep {...panel('agreements')} />
            </>
          ) : null}
          {phase.id === 'golive' ? <GoLiveStep tenantId={props.tenantId} detail={detail} onChanged={props.onChanged} onUnrecorded={props.onUnrecorded} onNotice={props.onNotice} funnel={funnel} step={step('golive')} onSelectPhase={props.onSelect} /> : null}
          {phase.done && phase.id !== 'golive' && nextPhase !== undefined ? (
            <div className={styles.actions}>
              <Button variant="primary" onClick={() => props.onSelect(nextPhase.id)}>
                {`Continue to ${nextPhase.title}`}
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <>
          <dl className={ts.summary}>
            {facts(phase.id, detail, consent, funnel).map(([label, value]) => (
              <div key={label} className={ts.summaryRow}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {editable ? (
            <button type="button" className={ts.changeLink} onClick={() => props.onOpen(phase.id)}>
              Change<span className={styles.srOnly}>{` ${phase.title.toLowerCase()}`}</span>
            </button>
          ) : null}
        </>
      )}
    </section>
  );
});
