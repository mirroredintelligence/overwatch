'use client';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { loadServiceChoices, type ServiceChoice } from '@/lib/lead/serviceChoices';
import styles from './Lead.module.css';

// Invite a reporter (W43). The invitation is texted, and says the set-up takes about three minutes. Only a
// service in the pilot can be invited: the back end's refusal shows the pilot words, not its own.

const MOBILE_EXAMPLE = 'Enter a UK mobile number, like 07700 900123';
const NOT_IN_PILOT = 'This service is not in the pilot scope list.';

const CHANNELS: [string, string][] = [
  ['push', 'App notification'],
  ['text', 'Text'],
  ['email', 'Email'],
];

export function InviteForm({ serviceId }: { serviceId?: string }) {
  const [services, setServices] = useState<ServiceChoice[] | null>(null);
  const [servicesFailed, setServicesFailed] = useState(false);
  const [service, setService] = useState(serviceId ?? '');
  const [role, setRole] = useState('');
  const [phone, setPhone] = useState('');
  const [channel, setChannel] = useState('text');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [noticeIsError, setNoticeIsError] = useState(false);
  const channelId = useId();

  useEffect(() => {
    let cancelled = false;
    loadServiceChoices()
      .then((list) => {
        if (!cancelled) setServices(list);
      })
      .catch(() => {
        if (!cancelled) setServicesFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const chosen = services?.find((choice) => choice.id === service)?.name ?? '';

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const problems: string[] = [];
    if (service === '') problems.push('Choose the service');
    if (role.trim() === '') problems.push('Enter the role, for example duty manager');
    if (!isUkMobile(phone)) problems.push(MOBILE_EXAMPLE);
    setErrors(problems);
    setNotice('');
    if (problems.length > 0) return;
    setBusy(true);
    const result = await leadPost('/api/bff/lead/invitations', { serviceId: service, role: role.trim(), phone, channel });
    setBusy(false);
    if (result.ok) {
      const ending = (result.body as { numberEnding?: unknown } | undefined)?.numberEnding;
      setNoticeIsError(false);
      setNotice(typeof ending === 'string' ? `Invitation sent. Sent to the number ending ${ending}.` : 'Invitation sent.');
      setPhone('');
      return;
    }
    setNoticeIsError(true);
    if (result.status === 409) setNotice(NOT_IN_PILOT);
    else if (result.status === 403) setNotice(CANNOT_DO);
    else setNotice('The invitation could not be sent. Try again.');
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Invite a reporter</h1>

      {errors.length > 0 ? (
        <div role="alert" className={styles.fieldError}>
          {errors.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      <form onSubmit={(event) => void submit(event)} noValidate className={styles.stack}>
        <div className={styles.field}>
          <label htmlFor="lead-invite-service" className={styles.fieldLabel}>
            Service
          </label>
          {servicesFailed ? (
            <p className={styles.fieldError}>The services could not be loaded.</p>
          ) : services === null ? (
            <p className={styles.muted}>Loading the services.</p>
          ) : (
            <select id="lead-invite-service" className={styles.input} value={service} onChange={(e) => setService(e.target.value)}>
              <option value="">Choose a service</option>
              {services.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className={styles.field}>
          <label htmlFor="lead-invite-role" className={styles.fieldLabel}>
            Role
          </label>
          <input id="lead-invite-role" className={styles.input} value={role} onChange={(e) => setRole(e.target.value)} />
        </div>

        <div className={styles.field}>
          <label htmlFor="lead-invite-phone" className={styles.fieldLabel}>
            Mobile number
          </label>
          <p className={styles.muted}>A ward or team phone is best</p>
          <input
            id="lead-invite-phone"
            className={styles.input}
            inputMode="tel"
            autoComplete="off"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>

        <fieldset className={styles.choices} aria-describedby={channelId}>
          <legend className={styles.fieldLabel}>Suggest how they report</legend>
          <p id={channelId} className={styles.muted}>
            They can change this during set-up.
          </p>
          {CHANNELS.map(([value, text]) => (
            <label key={value} className={styles.radio}>
              <input type="radio" name="invite-channel" value={value} checked={channel === value} onChange={() => setChannel(value)} />
              {text}
            </label>
          ))}
        </fieldset>

        <section className={styles.section} aria-labelledby="invite-preview-heading">
          <h2 id="invite-preview-heading" className={styles.sectionHeading}>
            The text we send
          </h2>
          <p className={styles.preview}>
            {`DIUCS: You are invited to report capacity for ${chosen || 'this service'}. Set up takes about 3 minutes: [link to set up] Valid for 48 hrs.`}
          </p>
        </section>

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-INVITE-SEND-BTN">
            Send invitation
          </Button>
        </div>
      </form>

      <p role={noticeIsError ? 'alert' : 'status'} className={noticeIsError ? styles.fieldError : styles.line}>
        {notice}
      </p>
    </main>
  );
}
