'use client';

import { useState } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { whenText } from '@/lib/tenantAdmin/words';
import { StatusTag } from '@/components/ui/StatusTag';
import styles from '@/components/admin/admin.module.css';
import gl from './GoLive.module.css';
import { useStep, type LifecycleProps } from './shared';

// The life of an organisation (TEN-083): suspend, resume and start closing. Each is asked for in a dialog that says what
// it does, and sent once with one idempotency key per submit.

const REASONS: readonly [string, string][] = [
  ['security-incident', 'Security incident'],
  ['information-governance', 'Information governance'],
  ['clinical-safety', 'Clinical safety'],
  ['contract', 'Contract'],
  ['operator-request', 'Operator request'],
];

type Step = 'activate' | 'suspend' | 'resume' | 'close' | null;

export function LifecyclePanel(props: LifecycleProps) {
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
    <Card heading="Look after it">
      <div className={gl.state}>
        {suspended ? <StatusTag variant="paused">Suspended</StatusTag> : <StatusTag variant="live">Live</StatusTag>}
        {suspended ? (
          <p className={`${styles.text} ${gl.stateText}`}>{`Suspended ${tenant.suspendMode === 'blocked' ? 'blocked' : 'read only'} since ${whenText(tenant.suspendedAt)}. Reason: ${(tenant.suspendReason ?? 'not recorded').replace(/-/g, ' ')}.`}</p>
        ) : (
          <p className={`${styles.text} ${gl.stateText}`}>The organisation is live.</p>
        )}
      </div>
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
          <TextField id="confirm-tenant" label="Type the organisation id to confirm (shown under Technical details in Organisation and sign-in)" value={typed} onChange={setTyped} requirement="none" autoComplete="off" />
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
