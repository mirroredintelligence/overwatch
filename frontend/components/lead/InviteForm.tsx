'use client';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { loadServiceChoices, type ServiceChoice } from '@/lib/lead/serviceChoices';
import { InvitePreview } from './InvitePreview';
import styles from './InviteForm.module.css';

// Invite a reporter (W43; INV-02). The compose panel of the reporters page: the form, and beside it the text the
// person will get. The invitation is texted, and says the set-up takes about three minutes. Only a service in the
// pilot can be invited: the back end's refusal shows the pilot words, not its own. The preview follows the form
// when a field is left, not on each key (it is a polite live region).

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
  const [shownService, setShownService] = useState(serviceId ?? '');
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

  const shownName = services?.find((choice) => choice.id === shownService)?.name ?? '';

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
    <section aria-labelledby="invite-heading" className={styles.panel}>
      <div className={styles.formSide}>
        <div>
          <h2 id="invite-heading" className={styles.title}>
            Invite a reporter
          </h2>
          <p className={styles.lede}>They set up in about 3 minutes, on their own phone.</p>
        </div>

        {errors.length > 0 ? (
          <div role="alert" className={`${styles.errors} ${styles.error}`}>
            {errors.map((message) => (
              <p key={message} className={styles.error}>
                {message}
              </p>
            ))}
          </div>
        ) : null}

        <form onSubmit={(event) => void submit(event)} onBlur={() => setShownService(service)} noValidate className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="lead-invite-service" className={styles.label}>
              Service
            </label>
            {servicesFailed ? (
              <p className={styles.error}>The services could not be loaded.</p>
            ) : services === null ? (
              <p className={styles.hint}>Loading the services.</p>
            ) : (
              <select id="lead-invite-service" className={styles.control} value={service} onChange={(e) => setService(e.target.value)}>
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
            <label htmlFor="lead-invite-role" className={styles.label}>
              Their role
            </label>
            <input id="lead-invite-role" className={styles.control} value={role} onChange={(e) => setRole(e.target.value)} />
          </div>

          <div className={styles.field}>
            <label htmlFor="lead-invite-phone" className={styles.label}>
              Mobile number
            </label>
            <p className={styles.hint}>A ward or team phone is best. It stays with the post, not the person.</p>
            <input
              id="lead-invite-phone"
              className={styles.control}
              inputMode="tel"
              autoComplete="off"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </div>

          <fieldset className={styles.field} aria-describedby={channelId}>
            <legend className={styles.label}>Suggest how they report</legend>
            <p id={channelId} className={styles.hint}>
              They can change this while setting up.
            </p>
            <div className={styles.chips}>
              {CHANNELS.map(([value, text]) => (
                <label key={value} className={styles.chip}>
                  <input type="radio" name="invite-channel" value={value} checked={channel === value} onChange={() => setChannel(value)} />
                  <span>{text}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className={styles.actions}>
            <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-INVITE-SEND-BTN">
              Send invitation
            </Button>
            <Button variant="neutral" href="/lead/reporters" dataEl="LEAD-INVITE-CANCEL-BTN">
              Cancel
            </Button>
          </div>
        </form>

        <p role={noticeIsError ? 'alert' : 'status'} className={styles.notice} data-failed={noticeIsError}>
          {notice}
        </p>
      </div>

      <InvitePreview service={shownName} />
    </section>
  );
}
