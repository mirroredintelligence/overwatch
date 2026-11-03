'use client';

import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { operatorSend } from '@/lib/operator/browser';
import type { ConsentRead, FunnelStep } from '@/lib/operator/funnel';
import type { parseTenantDetail } from '@/lib/operator/views';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';

// What the steps of an organisation's "Go live" page (TEN-083) share: the props each step gets, the section a step is
// drawn in, and the one write of a panel. Each step has its own file next to this one.

export type Detail = ReturnType<typeof parseTenantDetail>;
export type Say = { ok: boolean; text: string } | null;

export type PanelProps = {
  tenantId: string;
  detail: Detail;
  consent: ConsentRead;
  step: FunnelStep;
  /** This is the first step of its part that is not done: its main button is the part's one primary button. */
  isNext: boolean;
  /** The part has more than one step, so each step gets a heading. */
  heading: boolean;
  onChanged: () => void;
  onUnrecorded: () => void;
};

export function Said({ say }: { say: Say }) {
  if (say === null) return null;
  return (
    <p role={say.ok ? 'status' : 'alert'} className={say.ok ? styles.ok : styles.problem}>
      {say.text}
    </p>
  );
}

/** One step inside the selected part: its heading (when the part has several), its content and its closed technical details. */
export function StepSection({ step, heading, children, details }: { step: FunnelStep; heading: boolean; children: ReactNode; details?: ReactNode }) {
  const headingId = useId();
  return (
    <section className={ts.step} id={`step-${step.id}`} data-el={`OP-STEP-${step.id.toUpperCase()}`} data-state={step.done ? 'done' : 'todo'} aria-labelledby={heading ? headingId : undefined} aria-label={heading ? undefined : step.title}>
      {heading ? (
        <h3 id={headingId} className={ts.stepTitle}>
          {step.title}
        </h3>
      ) : null}
      {children}
      {details !== undefined ? (
        <details className={ts.disclosure}>
          <summary>Technical details</summary>
          <div className={ts.disclosureBody}>{details}</div>
        </details>
      ) : null}
    </section>
  );
}

export const E164 = /^\+[1-9]\d{6,14}$/;
export const WORK_EMAIL = /^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;
export const NUMBER_STATE: Record<string, string> = { active: 'In use', retired: 'Stopped', quarantined: 'On hold' };

export type MadeGroup = { role: string; name: string; groupId: string; created: boolean; assigned: boolean };
type RunData = { recorded?: boolean; expiresAt?: string; groups?: MadeGroup[]; added?: boolean };

/** One write of a panel: the key of this submit, busy, and what to say. */
export function useWrite(tenantId: string, props: Pick<PanelProps, 'onChanged' | 'onUnrecorded'>) {
  const submitKey = useSubmitKey();
  const [busy, setBusy] = useState(false);
  const [say, setSay] = useState<Say>(null);
  async function run(method: 'POST' | 'PUT', sub: string, body: unknown, done: (data: RunData) => string, failed: (status: number) => string): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setSay(null);
    const result = await operatorSend<RunData>(method, `/api/bff/platform/tenants/${tenantId}/${sub}`, body, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setSay({ ok: true, text: done(result.data) });
      if (result.data.recorded === false) props.onUnrecorded();
      props.onChanged();
      return true;
    }
    setSay({ ok: false, text: failed(result.status) });
    return false;
  }
  return { run, busy, say, setSay, fresh: submitKey.fresh };
}

export function isConsented(consent: ConsentRead): boolean {
  return consent.status === 'ok' && consent.data.invitation?.status === 'consented';
}

export const GROUP_FAILED = (status: number): string =>
  status === 404
    ? 'The teams could not be made. Check that their administrator has approved Overwatch.'
    : status === 503
      ? 'Their Microsoft account could not be reached. Try again in a minute.'
      : status === 409
        ? 'A team already gives a different role. Nothing was changed.'
        : 'The teams could not be made. Try again.';

/** The "add a person to a team by email" form shared by the administrators' team step and the other teams step. */
export function useMemberForm(props: PanelProps, role: () => string, noun: string) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const member = useWrite(props.tenantId, props);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const address = email.trim();
    if (!WORK_EMAIL.test(address) || address.includes('..')) {
      setError('Enter the person’s work email address, for example name@organisation.nhs.uk.');
      return;
    }
    setError(null);
    void member
      .run('POST', 'entra-groups/members', { role: role(), email: address }, (data) => (data.added === false ? `That person is already in the ${noun}.` : `Added to the ${noun}. The address is not kept.`), (status) =>
        status === 400
          ? 'No one in their Microsoft accounts has that email address.'
          : status === 404
            ? `That ${noun} has not been made yet.`
            : status === 503
              ? 'Their Microsoft account could not be reached. Try again in a minute.'
              : 'The person could not be added. Try again.',
      )
      .then((ok) => {
        if (ok) setEmail('');
      });
  }
  return { email, setEmail, error, member, submit };
}

// The life of the organisation (go live, suspend, resume, start closing) sends with a different shape: the outcome is
// passed up as a notice, because it outlives the panel (a tenant that has just been activated no longer has an
// activation panel). `recorded: false` is passed up too, and the step is never repeated.

export type Notice = { ok: boolean; text: string };
export type LifecycleProps = { tenantId: string; detail: Detail; onChanged: () => void; onNotice: (notice: Notice) => void; onUnrecorded: () => void };

export function useStep({ tenantId, onChanged, onNotice, onUnrecorded }: LifecycleProps) {
  const submitKey = useSubmitKey();
  const [busy, setBusy] = useState(false);
  async function run<T extends { recorded: boolean }>(method: 'POST' | 'DELETE', sub: string, body: unknown, done: (data: T) => string, failed: (status: number) => string): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    const result = await operatorSend<T>(method, `/api/bff/platform/tenants/${tenantId}/${sub}`, body, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    if (result.ok) {
      onNotice({ ok: true, text: done(result.data) });
      if (!result.data.recorded) onUnrecorded();
      onChanged();
      return true;
    }
    onNotice({ ok: false, text: failed(result.status) });
    if (result.status === 409) onChanged();
    return false;
  }
  return { run, busy };
}
