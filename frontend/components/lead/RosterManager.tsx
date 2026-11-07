'use client';

import { type FormEvent, useCallback, useEffect, useId, useState } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { leadPost, leadRead } from '@/lib/lead/browser';
import { clockTime } from '@/lib/lead/format';
import { parseRoster, type Roster, shiftWords } from '@/lib/lead/roster';
import { CheckInCode } from './CheckInCode';
import styles from './RosterManager.module.css';

// The duty roster of one service (DEC-1341): who is pre-registered to report for it, who is on shift now, and a way to
// add or remove a person. A duty manager texts ON (or ON 8 for eight hours) when they start and OFF when they finish;
// the newest ON replaces the last. A person who is off shift is sent no prompt. What a press did is said on this
// page, next to the press. The number is never shown back: only its last four digits.

type State = { kind: 'loading' } | { kind: 'ready'; roster: Roster } | { kind: 'failed' };
type Message = { text: string; failed: boolean } | null;

const NAME_MIN = 2;
const NAME_MAX = 60;

export function RosterManager({ serviceId }: { serviceId: string }) {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');
  const [errors, setErrors] = useState<{ name?: string; mobile?: string }>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const nameId = useId();
  const mobileId = useId();
  const path = `/api/bff/lead/services/${encodeURIComponent(serviceId)}/roster`;

  const read = useCallback(async () => {
    const reply = await leadRead(path);
    if (!reply.ok) return { kind: 'failed' } as const;
    try {
      return { kind: 'ready', roster: parseRoster(reply.body) } as const;
    } catch {
      return { kind: 'failed' } as const;
    }
  }, [path]);

  useEffect(() => {
    let live = true;
    read().then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, [read]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    const next: { name?: string; mobile?: string } = {};
    if (trimmed.length < NAME_MIN || trimmed.length > NAME_MAX) next.name = `Enter a name, ${NAME_MIN} to ${NAME_MAX} characters.`;
    if (!isUkMobile(mobile)) next.mobile = 'Enter a UK mobile number, for example 07700 900123.';
    setErrors(next);
    if (next.name !== undefined || next.mobile !== undefined) return;
    setBusy(true);
    setMessage(null);
    const result = await leadPost(path, { name: trimmed, mobile });
    setBusy(false);
    if (result.ok) {
      setName('');
      setMobile('');
      setMessage({ text: `Added ${trimmed}. They are off shift until they text ON.`, failed: false });
      setState(await read());
      return;
    }
    setMessage({
      text:
        result.status === 409
          ? 'That person is already on this roster.'
          : 'The person could not be added. Check the details and try again.',
      failed: true,
    });
  }

  async function remove(roleId: string, who: string) {
    setBusy(true);
    setMessage(null);
    const result = await leadPost(`/api/bff/lead/roster/${encodeURIComponent(roleId)}/remove`);
    setBusy(false);
    setConfirming(null);
    if (result.ok) {
      setMessage({ text: `Removed ${who} from the roster.`, failed: false });
      setState(await read());
      return;
    }
    setMessage({ text: 'The person could not be removed. Try again.', failed: true });
  }

  return (
    <main>
      <div data-noprint>
      <PageHeader title="Duty managers">
        <p className={styles.lead}>
          Who may report for this service. A duty manager texts ON when they start, or ON 8 for eight hours, and OFF when
          they finish. Someone texting ON replaces whoever was on. A person who is off shift is sent no prompt.
        </p>
      </PageHeader>

      {state.kind === 'loading' ? (
        <Loading label="Loading the roster.">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}
      {state.kind === 'failed' ? <p role="alert" className={styles.failed}>The roster could not be read. Try again.</p> : null}

      {state.kind === 'ready' ? (
        <section className={styles.card} aria-labelledby="roster-heading" data-el="LEAD-ROSTER">
          <h2 id="roster-heading" className={styles.heading}>
            On the roster
          </h2>
          {state.roster.managers.length === 0 ? (
            <p className={styles.none}>No one is on the roster yet. Add the people who report for this service.</p>
          ) : (
            <ul className={styles.rows}>
              {state.roster.managers.map((manager) => (
                <li key={manager.roleId} className={styles.row}>
                  <div className={styles.who}>
                    <span className={styles.name}>{manager.name}</span>
                    <span className={styles.detail}>
                      {`${manager.numberEnding === null ? 'No number' : `Number ending ${manager.numberEnding}`} · ${shiftWords(manager, clockTime)}`}
                    </span>
                  </div>
                  {confirming === manager.roleId ? (
                    <div className={styles.actions}>
                      <Button variant="neutral" busy={busy} onClick={() => void remove(manager.roleId, manager.name)} ariaLabel={`Remove ${manager.name} now`}>
                        Remove
                      </Button>
                      <Button variant="secondary" onClick={() => setConfirming(null)}>
                        Keep
                      </Button>
                    </div>
                  ) : (
                    <Button variant="secondary" onClick={() => setConfirming(manager.roleId)} ariaLabel={`Remove ${manager.name} from the roster`}>
                      Remove
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      <section className={styles.card} aria-labelledby="roster-add-heading">
        <h2 id="roster-add-heading" className={styles.heading}>
          Add a duty manager
        </h2>
        <form onSubmit={add} noValidate className={styles.form}>
          <div className={styles.field}>
            <label htmlFor={nameId} className={styles.label}>
              Name
            </label>
            <input
              id={nameId}
              className={styles.input}
              value={name}
              autoComplete="off"
              aria-invalid={errors.name ? 'true' : undefined}
              aria-describedby={errors.name ? `${nameId}-error` : undefined}
              onChange={(event) => setName(event.target.value)}
            />
            {errors.name ? (
              <p id={`${nameId}-error`} className={styles.error}>
                {errors.name}
              </p>
            ) : null}
          </div>
          <div className={styles.field}>
            <label htmlFor={mobileId} className={styles.label}>
              Mobile number
            </label>
            <input
              id={mobileId}
              className={styles.input}
              type="tel"
              inputMode="tel"
              value={mobile}
              autoComplete="off"
              aria-invalid={errors.mobile ? 'true' : undefined}
              aria-describedby={errors.mobile ? `${mobileId}-error` : undefined}
              onChange={(event) => setMobile(event.target.value)}
            />
            {errors.mobile ? (
              <p id={`${mobileId}-error`} className={styles.error}>
                {errors.mobile}
              </p>
            ) : null}
          </div>
          <Button type="submit" variant="primary" busy={busy} dataEl="LEAD-ROSTER-ADD-BTN">
            Add to the roster
          </Button>
        </form>
        {message === null ? null : (
          <p role="status" className={styles.message} data-failed={message.failed || undefined} data-el="LEAD-ROSTER-MESSAGE">
            {message.text}
          </p>
        )}
      </section>

      <p className={styles.back}>
        <a href="/lead">Back to the overview</a>
      </p>
      </div>

      <CheckInCode serviceId={serviceId} />
    </main>
  );
}
