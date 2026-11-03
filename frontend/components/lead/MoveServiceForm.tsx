'use client';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { LadderTimeline, type LadderStep } from '@/components/blocks/LadderTimeline';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { loadServiceChoices, type ServiceChoice } from '@/lib/lead/serviceChoices';
import styles from './MoveServiceForm.module.css';

// Move a service to another phone (W43). The new phone gets a code; the lead phones the service on the number
// from the register; then the service reports to the new phone. The old phone keeps its other services. Nothing
// moves until step 3, and the three steps stay in view while the form is filled in.

const MOBILE_EXAMPLE = 'Enter a UK mobile number, like 07700 900123';
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HEADING_STEPS = 'Three steps, in this order';

export function MoveServiceForm({ serviceId }: { serviceId?: string }) {
  const [services, setServices] = useState<ServiceChoice[] | null>(null);
  const [servicesFailed, setServicesFailed] = useState(false);
  const [service, setService] = useState(serviceId ?? '');
  const [phone, setPhone] = useState('');
  const [how, setHow] = useState<'changed' | 'date' | null>(null);
  const [date, setDate] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [notice, setNotice] = useState('');
  const [noticeIsError, setNoticeIsError] = useState(false);
  const phoneHintId = useId();

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
      setSent(true);
      setNoticeIsError(false);
      setNotice('The move has started.');
      return;
    }
    setNoticeIsError(true);
    setNotice(result.status === 403 ? CANNOT_DO : 'The move could not be started. Try again.');
  }

  const steps: LadderStep[] = [
    {
      id: 'code',
      time: 'Step 1',
      title: 'We text the new phone a code',
      detail: 'It goes to the new phone straight away. It works for ten minutes.',
      state: sent ? 'done' : 'open',
    },
    {
      id: 'call',
      time: 'Step 2',
      title: 'You phone the service',
      detail: 'Use the number from the register, not the new phone. Check it really is them.',
      state: 'open',
    },
    {
      id: 'move',
      time: 'Step 3',
      title: 'The service goes to the new phone',
      detail: 'Prompts and reports go there until the cover ends.',
      state: 'open',
    },
  ];

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-label="Move">
        <h1 className={styles.title}>Move a service to another phone</h1>

        {errors.length > 0 ? (
          <div role="alert" className={styles.fieldError}>
            {errors.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </div>
        ) : null}

        <form onSubmit={(event) => void submit(event)} noValidate className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="lead-move-service" className={styles.label}>
              Which service?
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
            <label htmlFor="lead-move-phone" className={styles.label}>
              To which phone?
            </label>
            <input
              id="lead-move-phone"
              className={styles.input}
              inputMode="tel"
              autoComplete="off"
              aria-describedby={phoneHintId}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
            <p id={phoneHintId} className={styles.hint}>
              A UK mobile number. We text it a code. The old phone keeps its other services.
            </p>
          </div>

          <fieldset className={styles.fieldset}>
            <legend className={styles.label}>For how long?</legend>
            <div className={styles.chips}>
              <label className={styles.chip} data-selected={how === 'changed'}>
                <input type="radio" name="move-how" checked={how === 'changed'} onChange={() => setHow('changed')} />
                For good
                {how === 'changed' ? <Tick /> : null}
              </label>
              <label className={styles.chip} data-selected={how === 'date'}>
                <input type="radio" name="move-how" checked={how === 'date'} onChange={() => setHow('date')} />
                For a while
                {how === 'date' ? <Tick /> : null}
              </label>
            </div>
            {how === 'date' ? (
              <div className={styles.field}>
                <label htmlFor="lead-move-date" className={styles.label}>
                  Cover ends on
                </label>
                <input id="lead-move-date" className={`${styles.input} ${styles.dateInput}`} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </div>
            ) : null}
          </fieldset>

          <div className={styles.footer}>
            <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-MOVE-START-BTN">
              Start the move
            </Button>
            <Button variant="neutral" href="/lead/phones" dataEl="LEAD-MOVE-CANCEL-LINK">
              Cancel
            </Button>
          </div>
        </form>

        <p role={noticeIsError ? 'alert' : 'status'} className={noticeIsError ? styles.fieldError : styles.line}>
          {notice}
        </p>
      </section>

      <aside className={styles.side} aria-label="What happens next">
        <p className={styles.kicker}>What happens next</p>
        <h2 className={styles.sideTitle}>{HEADING_STEPS}</h2>
        <LadderTimeline label={HEADING_STEPS} steps={steps} stateWords={{ open: 'To do', done: 'Sent' }} />
        <p className={styles.sideNote}>Nothing moves until step 3. If you stop part-way, the service stays where it is.</p>
      </aside>
    </main>
  );
}

function Tick() {
  return (
    <svg className={styles.tick} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M4 10.5l4 4 8-8.5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
