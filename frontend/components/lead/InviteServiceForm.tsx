'use client';

import { useId, useState, type FormEvent } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { bffPost } from '@/lib/bff/client';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import { CATEGORY_CODES, NAME_MAX_LENGTH, categoryLabel } from '@/lib/registration/model';
import styles from './InviteServiceForm.module.css';

// Invite a service (DEC-1341 item 1a). The shift lead gives the service's name and kind and the name and mobile number of
// the service lead. The service goes on the scope list as in the pilot and the service lead is texted a link to set it up
// (hours, criteria, districts) and send it for review; the duty managers who report are added afterwards on the roster.
// It is the two steps the scope list and the reporter invitation already are, in one press. If the second step fails the
// service is already on the list, and the page says so and links to the invitation for it, so a retry makes no second entry.

type Errors = Partial<Record<'name' | 'category' | 'person' | 'mobile', string>>;
type Outcome =
  | { kind: 'none' }
  | { kind: 'sent'; service: string; ending: string | null }
  | { kind: 'half'; serviceId: string; service: string; message: string };

const ROLE_LABEL = 'Service lead';

function idOf(data: unknown): string | null {
  return typeof data === 'object' && data !== null && 'serviceId' in data && typeof data.serviceId === 'string' ? data.serviceId : null;
}

export function InviteServiceForm() {
  const ids = useId();
  const [name, setName] = useState('');
  const [category, setCategory] = useState('');
  const [person, setPerson] = useState('');
  const [mobile, setMobile] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>({ kind: 'none' });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Errors = {};
    const service = name.trim();
    if (service === '' || service.length > NAME_MAX_LENGTH) found.name = 'Enter the service name';
    if (category === '') found.category = 'Choose a category';
    if (person.trim().length < 2) found.person = 'Enter the name of the service lead';
    if (!isUkMobile(mobile)) found.mobile = 'Enter a UK mobile number, like 07700 900123';
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setBusy(true);
    setFailure(null);
    const added = await bffPost('/api/bff/scope', { name: service, category, flag: 'in-pilot' });
    const serviceId = added.ok ? idOf(added.data) : null;
    if (serviceId === null) {
      setBusy(false);
      setFailure('The service could not be added. Check the details and try again.');
      return;
    }
    const invited = await leadPost('/api/bff/lead/invitations', { serviceId, role: ROLE_LABEL, phone: mobile, channel: 'text' });
    setBusy(false);
    if (invited.ok) {
      const ending = (invited.body as { numberEnding?: unknown } | undefined)?.numberEnding;
      setOutcome({ kind: 'sent', service, ending: typeof ending === 'string' ? ending : null });
      setName('');
      setCategory('');
      setPerson('');
      setMobile('');
      return;
    }
    setOutcome({
      kind: 'half',
      serviceId,
      service,
      message: invited.status === 403 ? CANNOT_DO : 'The invitation could not be sent.',
    });
  }

  if (outcome.kind === 'sent') {
    return (
      <main className={styles.page}>
        <PageHeader title="Invite a service" />
        <section className={styles.card} role="status" data-el="LEAD-INVITE-SERVICE-SENT">
          <h2 className={styles.heading}>Invitation sent</h2>
          <p className={styles.body}>
            {outcome.service} is on the scope list.{' '}
            {outcome.ending === null ? 'The service lead has been texted a link.' : `The service lead has been texted a link, at the number ending ${outcome.ending}.`}{' '}
            They set the service up and send it for review. Add its duty managers on the roster once it is set up.
          </p>
          <div className={styles.actions}>
            <Button variant="primary" href="/lead/reporters" dataEl="LEAD-INVITE-SERVICE-PROGRESS-LINK">
              See set-up progress
            </Button>
            <Button variant="secondary" onClick={() => setOutcome({ kind: 'none' })} dataEl="LEAD-INVITE-SERVICE-ANOTHER-BTN">
              Invite another service
            </Button>
          </div>
        </section>
      </main>
    );
  }

  if (outcome.kind === 'half') {
    return (
      <main className={styles.page}>
        <PageHeader title="Invite a service" />
        <section className={styles.card} role="alert" data-el="LEAD-INVITE-SERVICE-HALF">
          <h2 className={styles.heading}>{outcome.service} was added, but not invited</h2>
          <p className={styles.body}>{outcome.message} The service is on the scope list. Send the invitation from its own page.</p>
          <div className={styles.actions}>
            <Button variant="primary" href={`/lead/reporters/invite?service=${encodeURIComponent(outcome.serviceId)}`} dataEl="LEAD-INVITE-SERVICE-RETRY-LINK">
              Invite the service lead
            </Button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <PageHeader title="Invite a service">
        <p className={styles.lede}>
          The service lead is texted a link and sets the service up themselves: hours, criteria and districts. They send it for review, and you add its duty
          managers afterwards.
        </p>
      </PageHeader>
      <section className={styles.card} aria-labelledby={`${ids}-heading`}>
        <h2 id={`${ids}-heading`} className={styles.heading}>
          The service and its lead
        </h2>
        {failure !== null ? (
          <p role="alert" className={styles.error}>
            {failure}
          </p>
        ) : null}
        <form onSubmit={(event) => void submit(event)} noValidate className={styles.form} data-el="LEAD-INVITE-SERVICE-FORM">
          <div className={styles.field}>
            <label htmlFor={`${ids}-name`} className={styles.label}>
              Service name
            </label>
            <input
              id={`${ids}-name`}
              className={styles.input}
              value={name}
              maxLength={NAME_MAX_LENGTH}
              autoComplete="off"
              aria-invalid={errors.name !== undefined || undefined}
              aria-describedby={errors.name !== undefined ? `${ids}-name-error` : undefined}
              onChange={(event) => setName(event.target.value)}
            />
            {errors.name !== undefined ? <p id={`${ids}-name-error`} className={styles.error}>{errors.name}</p> : null}
          </div>
          <fieldset className={styles.group} aria-describedby={errors.category !== undefined ? `${ids}-category-error` : undefined}>
            <legend className={styles.label}>Category</legend>
            <div className={styles.chips}>
              {CATEGORY_CODES.map((code) => (
                <label key={code} className={styles.chip}>
                  <input type="radio" name={`${ids}-category`} value={code} checked={category === code} onChange={() => setCategory(code)} />
                  {categoryLabel(code)}
                </label>
              ))}
            </div>
            {errors.category !== undefined ? <p id={`${ids}-category-error`} className={styles.error}>{errors.category}</p> : null}
          </fieldset>
          <div className={styles.field}>
            <label htmlFor={`${ids}-person`} className={styles.label}>
              Service lead&apos;s name
            </label>
            <input
              id={`${ids}-person`}
              className={styles.input}
              value={person}
              autoComplete="off"
              aria-invalid={errors.person !== undefined || undefined}
              aria-describedby={errors.person !== undefined ? `${ids}-person-error` : undefined}
              onChange={(event) => setPerson(event.target.value)}
            />
            {errors.person !== undefined ? <p id={`${ids}-person-error`} className={styles.error}>{errors.person}</p> : null}
          </div>
          <div className={styles.field}>
            <label htmlFor={`${ids}-mobile`} className={styles.label}>
              Service lead&apos;s mobile number
            </label>
            <input
              id={`${ids}-mobile`}
              className={styles.input}
              type="tel"
              inputMode="tel"
              value={mobile}
              autoComplete="off"
              aria-invalid={errors.mobile !== undefined || undefined}
              aria-describedby={errors.mobile !== undefined ? `${ids}-mobile-error` : undefined}
              onChange={(event) => setMobile(event.target.value)}
            />
            {errors.mobile !== undefined ? <p id={`${ids}-mobile-error`} className={styles.error}>{errors.mobile}</p> : null}
          </div>
          <Button type="submit" variant="primary" busy={busy} dataEl="LEAD-INVITE-SERVICE-BTN">
            Send the invitation
          </Button>
        </form>
      </section>
    </main>
  );
}
