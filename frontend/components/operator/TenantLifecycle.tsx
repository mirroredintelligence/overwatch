'use client';

import { useState } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { operatorSend } from '@/lib/operator/browser';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { whenText } from '@/lib/tenantAdmin/words';
import type { Funnel, FunnelStep } from '@/lib/operator/funnel';
import type { Detail } from './TenantPanels';
import styles from '@/components/admin/admin.module.css';

// The last step of the Go live page, and the life of an organisation (TEN-083): go live, suspend, resume and start closing.
// Each is asked for in a dialog that says what it does, and sent once with one idempotency key per submit.
// The outcome is passed up as a notice (it outlives the panel: a tenant that has just been activated no
// longer has an activation panel). `recorded: false` is passed up too, and the step is never repeated.

export type Notice = { ok: boolean; text: string };
type Props = { tenantId: string; detail: Detail; onChanged: () => void; onNotice: (notice: Notice) => void; onUnrecorded: () => void };

const REASONS: readonly [string, string][] = [
  ['security-incident', 'Security incident'],
  ['information-governance', 'Information governance'],
  ['clinical-safety', 'Clinical safety'],
  ['contract', 'Contract'],
  ['operator-request', 'Operator request'],
];

type Step = 'activate' | 'suspend' | 'resume' | 'close' | null;

function useStep({ tenantId, onChanged, onNotice, onUnrecorded }: Props) {
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

export function GoLiveStep(props: Props & { funnel: Funnel; step: FunnelStep }) {
  const [asking, setAsking] = useState(false);
  const { run, busy } = useStep(props);
  const { funnel, step } = props;
  const status = props.detail.tenant.status;
  async function goLive() {
    setAsking(false);
    await run('POST', 'activation', undefined, () => 'The organisation is live.', () => 'It cannot go live yet. The page has been read again.');
  }
  const state = step.done ? 'done' : funnel.next === 'golive' ? 'next' : 'todo';
  return (
    <div id="step-golive" data-el="OP-STEP-GOLIVE" data-state={state}>
      <Card heading={step.title}>
        <p className={styles.row}>
          <span className={styles.muted}>{`Step ${step.number} of ${funnel.total}`}</span>
          <span className={step.done ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{state === 'done' ? 'Done' : state === 'next' ? 'Next' : 'To do'}</span>
        </p>
        {status !== 'provisioning' ? (
          <p className={styles.ok}>{`This organisation is live${props.detail.tenant.activatedAt !== null ? ` since ${whenText(props.detail.tenant.activatedAt)}` : ''}.`}</p>
        ) : funnel.canGoLive ? (
          <>
            <p className={styles.text}>Every step is done. Once it is live, their people can sign in.</p>
            <div className={styles.actions}>
              <Button variant="primary" busy={busy} onClick={() => setAsking(true)} dataEl="OP-ACTIVATE-BTN">
                Go live
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className={styles.text}>Going live is not available until every step above is done. Still to do:</p>
            <ul className={styles.list} aria-label="Still to do">
              {funnel.missing.map((m) => (
                <li key={`${m.step}-${m.words}`}>{`${m.words} (${funnel.steps.find((s) => s.id === m.step)?.title ?? 'Go live'}, step ${funnel.steps.find((s) => s.id === m.step)?.number ?? funnel.total})`}</li>
              ))}
            </ul>
          </>
        )}
        {asking ? (
          <Dialog title="Go live with this organisation?" sub="Its people will be able to sign in." onClose={() => setAsking(false)}>
            <div className={styles.actions}>
              <Button variant="primary" onClick={() => void goLive()}>
                Yes, go live
              </Button>
              <Button variant="neutral" onClick={() => setAsking(false)}>
                Cancel
              </Button>
            </div>
          </Dialog>
        ) : null}
      </Card>
    </div>
  );
}

export function LifecyclePanel(props: Props) {
  const [step, setStep] = useState<Step>(null);
  const [mode, setMode] = useState<'read-only' | 'blocked'>('read-only');
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState('');
  const [typed, setTyped] = useState('');
  const { run, busy } = useStep(props);
  const tenant = props.detail.tenant;
  const active = tenant.status === 'active';
  const suspended = tenant.status === 'suspended';
  if (!active && !suspended) return null;

  const close = () => {
    setStep(null);
    setProblem('');
    setTyped('');
  };

  async function suspend() {
    if (reason === '') {
      setProblem('Choose a reason.');
      return;
    }
    close();
    await run('POST', 'suspension', { mode, reason }, () => 'The organisation is suspended.', () => 'The organisation could not be suspended. The page has been read again.');
  }
  async function resume() {
    close();
    await run<{ recorded: boolean; servicesPrompted: number; servicesAnnounced: number }>(
      'DELETE',
      'suspension',
      undefined,
      (d) => `The organisation is resumed. ${d.servicesPrompted} ${d.servicesPrompted === 1 ? 'service was' : 'services were'} prompted and ${d.servicesAnnounced} announced.`,
      () => 'The organisation could not be resumed. The page has been read again.',
    );
  }
  async function closing() {
    const confirm = typed;
    close();
    await run<{ recorded: boolean; noticeEndsAt: string }>('POST', 'offboarding', { confirm }, (d) => `Closing has started. The notice ends ${whenText(d.noticeEndsAt)}.`, () => 'Closing could not be started. The page has been read again.');
  }

  return (
    <Card heading="Suspend or close this organisation">
      {suspended ? (
        <p className={styles.text}>{`Suspended ${tenant.suspendMode === 'blocked' ? 'blocked' : 'read only'} since ${whenText(tenant.suspendedAt)}. Reason: ${(tenant.suspendReason ?? 'not recorded').replace(/-/g, ' ')}.`}</p>
      ) : (
        <p className={styles.text}>The organisation is live.</p>
      )}
      <div className={styles.actions}>
        {active ? (
          <Button variant="secondary" busy={busy} onClick={() => setStep('suspend')} dataEl="OP-SUSPEND-BTN">
            Suspend
          </Button>
        ) : null}
        {suspended ? (
          <Button variant="primary" busy={busy} onClick={() => setStep('resume')} dataEl="OP-RESUME-BTN">
            Resume
          </Button>
        ) : null}
        <Button variant="neutral" busy={busy} onClick={() => setStep('close')} dataEl="OP-CLOSE-BTN">
          Start closing the organisation
        </Button>
      </div>

      {step === 'suspend' ? (
        <Dialog title="Suspend this organisation?" sub="Its people are affected at once." onClose={close}>
          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>Mode</legend>
            <label className={styles.check}>
              <input type="radio" name="mode" checked={mode === 'read-only'} onChange={() => setMode('read-only')} />
              Read only: people can look but nobody can change anything.
            </label>
            <label className={styles.check}>
              <input type="radio" name="mode" checked={mode === 'blocked'} onChange={() => setMode('blocked')} />
              Blocked: nobody can sign in. Use this for a security incident.
            </label>
          </fieldset>
          <div className={styles.selectLabel}>
            <label htmlFor="suspend-reason">Reason</label>
            <select id="suspend-reason" className={styles.select} value={reason} onChange={(event) => setReason(event.target.value)}>
              <option value="">Choose a reason</option>
              {REASONS.map(([code, word]) => (
                <option key={code} value={code}>
                  {word}
                </option>
              ))}
            </select>
          </div>
          {problem !== '' ? <p className={styles.problem}>{problem}</p> : null}
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => void suspend()}>
              Confirm suspension
            </Button>
            <Button variant="neutral" onClick={close}>
              Cancel
            </Button>
          </div>
        </Dialog>
      ) : null}

      {step === 'resume' ? (
        <Dialog title="Resume this organisation?" sub="Its people can use it again. Its services are prompted for their figures." onClose={close}>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => void resume()}>
              Confirm resume
            </Button>
            <Button variant="neutral" onClick={close}>
              Cancel
            </Button>
          </div>
        </Dialog>
      ) : null}

      {step === 'close' ? (
        <Dialog title="Start closing this organisation?" onClose={close}>
          <p className={styles.warn}>
            Its people cannot sign in from now on. A notice period of 30 days starts. Exporting its data is not built yet, so nothing can be handed back to them.
          </p>
          <TextField id="confirm-tenant" label="Type the organisation id to confirm (shown under Details in step 1)" value={typed} onChange={setTyped} requirement="none" autoComplete="off" />
          <div className={styles.actions}>
            <Button variant="primary" disabled={typed !== tenant.id} onClick={() => void closing()}>
              Start closing
            </Button>
            <Button variant="neutral" onClick={close}>
              Cancel
            </Button>
          </div>
        </Dialog>
      ) : null}
    </Card>
  );
}
