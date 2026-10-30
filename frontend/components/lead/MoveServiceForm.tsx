'use client';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { loadServiceChoices, type ServiceChoice } from '@/lib/lead/serviceChoices';
import styles from './Lead.module.css';

// Move a service to another phone (W43). The new phone gets a code; the lead phones the service on the number
// from the register; then the service reports to the new phone. The old phone keeps its other services.

const MOBILE_EXAMPLE = 'Enter a UK mobile number, like 07700 900123';
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function MoveServiceForm({ serviceId }: { serviceId?: string }) {
  const [services, setServices] = useState<ServiceChoice[] | null>(null);
  const [servicesFailed, setServicesFailed] = useState(false);
  const [service, setService] = useState(serviceId ?? '');
  const [phone, setPhone] = useState('');
  const [how, setHow] = useState<'changed' | 'date' | null>(null);
  const [date, setDate] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [noticeIsError, setNoticeIsError] = useState(false);
  const howId = useId();

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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const problems: string[] = [];
    if (service === '') problems.push('Choose the service to move');
    if (!isUkMobile(phone)) problems.push(MOBILE_EXAMPLE);
    if (how === null) problems.push('Choose how long the move lasts');
    if (how === 'date' && !DATE.test(date)) problems.push('Choose the date the cover ends');
    setErrors(problems);
    setNotice('');
    if (problems.length > 0) return;
    const body = how === 'date' ? { toPhone: phone, until: 'date', date } : { toPhone: phone, until: 'changed' };
    setBusy(true);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(service)}/move`, body);
    setBusy(false);
    if (result.ok) {
      setNoticeIsError(false);
      setNotice('The move has started.');
      return;
    }
    setNoticeIsError(true);
    setNotice(result.status === 403 ? CANNOT_DO : 'The move could not be started. Try again.');
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Move a service</h1>

      {errors.length > 0 ? (
        <div role="alert" className={styles.fieldError}>
          {errors.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      <form onSubmit={(event) => void submit(event)} noValidate className={styles.stack}>
        <div className={styles.field}>
          <label htmlFor="lead-move-service" className={styles.fieldLabel}>
            Service
          </label>
          {servicesFailed ? (
            <p className={styles.fieldError}>The services could not be loaded.</p>
          ) : services === null ? (
            <p className={styles.muted}>Loading the services.</p>
          ) : (
            <select id="lead-move-service" className={styles.input} value={service} onChange={(e) => setService(e.target.value)}>
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
          <label htmlFor="lead-move-phone" className={styles.fieldLabel}>
            To mobile number
          </label>
          <input
            id="lead-move-phone"
            className={styles.input}
            inputMode="tel"
            autoComplete="off"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>

        <fieldset className={styles.choices} aria-describedby={howId}>
          <legend className={styles.fieldLabel}>How long?</legend>
          <label className={styles.radio}>
            <input type="radio" name="move-how" checked={how === 'changed'} onChange={() => setHow('changed')} />
            Until I change it
          </label>
          <label className={styles.radio}>
            <input type="radio" name="move-how" checked={how === 'date'} onChange={() => setHow('date')} />
            Cover until a date
          </label>
          {how === 'date' ? (
            <div className={styles.field}>
              <label htmlFor="lead-move-date" className={styles.fieldLabel}>
                Cover ends on
              </label>
              <input id="lead-move-date" className={styles.input} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
          ) : null}
        </fieldset>

        <section className={styles.section} aria-labelledby="move-steps-heading">
          <h2 id="move-steps-heading" className={styles.sectionHeading}>
            What happens next
          </h2>
          <ol className={styles.steps}>
            <li>We text the new phone a code</li>
            <li>You phone the service on the number from the register</li>
            <li>The service goes to the new phone</li>
          </ol>
          <p className={styles.muted}>The old phone keeps its other services.</p>
        </section>

        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-MOVE-START-BTN">
            Start the move
          </Button>
        </div>
      </form>

      <p role={noticeIsError ? 'alert' : 'status'} className={noticeIsError ? styles.fieldError : styles.line}>
        {notice}
      </p>
    </main>
  );
}
