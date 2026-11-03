'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { listOf, textOf } from '@/lib/lead/answers';
import { leadGet, leadPost, leadRead, newIdempotencyKey } from '@/lib/lead/browser';
import { SETUP_STEPS, stuckAt, type SetupSteps } from '@/lib/lead/setupProgress';
import { ReporterDetail } from './ReporterDetail';
import { ReporterList } from './ReporterList';
import { ReporterStage } from './ReporterStage';
import type { Invitation } from './SetupTracker';
import styles from './ChangeNumberForm.module.css';
import stageStyles from './ReporterStage.module.css';

// Change a reporter's number for leave or cover (W18, pilot; INV-03). It is the Detail state of the reporters
// page with the "Change their number" row open: the list of invitations stays, and the row sits among the
// open reporter's actions. A reporter whose set-up is complete has no actions, and a service with no invitation
// has no detail, so there the same row is on a card. The old number stops working as soon as the change is
// saved. The full new number is never shown back: the answer carries the last four digits only, and the field
// is cleared once the change is saved (H-331).

const REPORTERS = '/lead/reporters';

const COVERS: [string, string][] = [
  ['today', 'Today'],
  ['this-week', 'This week'],
  ['until-changed', 'Until I change it'],
];

type Choice = { id: string; name: string };

function choicesFrom(value: unknown): Choice[] {
  const list = (value as { services?: unknown } | undefined)?.services;
  if (!Array.isArray(list)) return [];
  return list.filter(
    (item): item is Choice =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as Choice).id === 'string' &&
      typeof (item as Choice).name === 'string',
  );
}

/** The invitations, read as SetupTracker reads them (its parser is not exported). */
function invitationsFrom(body: unknown): Invitation[] {
  return listOf(body, 'items').map((item) => {
    const row = item as Record<string, unknown>;
    const steps = row.steps as Record<string, unknown>;
    const flags = {} as SetupSteps;
    for (const step of SETUP_STEPS) {
      if (typeof steps?.[step] !== 'boolean') throw new Error('step');
      flags[step] = steps[step] as boolean;
    }
    return {
      id: textOf(row.id),
      serviceId: textOf(row.serviceId),
      serviceName: textOf(row.serviceName),
      role: textOf(row.role),
      steps: flags,
      invitedAt: textOf(row.invitedAt),
      lastSeen: textOf(row.lastSeen),
      firstReportAt: typeof row.firstReportAt === 'string' ? row.firstReportAt : null,
    };
  });
}

/** The last four digits of the service's current number, read for the service it was read for. */
type Reading = { service: string; ending: string | null };

function endingOf(value: unknown): string | null {
  const posts = (value as { reporters?: unknown } | undefined)?.reporters;
  if (!Array.isArray(posts) || posts.length === 0) return null;
  const ending = (posts[0] as { numberEnding?: unknown } | undefined)?.numberEnding;
  return typeof ending === 'string' ? ending : null;
}

type RowProps = {
  serviceId?: string;
  /** Show the service choice (the card), or take the service as given (the open reporter). */
  withChoice: boolean;
  onNotice: (text: string, failed: boolean) => void;
};

function NumberRow({ serviceId, withChoice, onNotice }: RowProps) {
  const [services, setServices] = useState<Choice[]>([]);
  const [service, setService] = useState<string>(serviceId ?? '');
  const [reading, setReading] = useState<Reading | null>(null);
  const [mobile, setMobile] = useState('');
  const [until, setUntil] = useState<string | null>(null);
  const [mobileError, setMobileError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const keyRef = useRef<string | null>(null);
  const mobileId = useId();
  const groupId = useId();
  const panelId = useId();
  const serviceFieldId = useId();

  useEffect(() => {
    if (!withChoice) return;
    let cancelled = false;
    leadGet('/api/bff/lead/services')
      .then((value) => {
        if (!cancelled) setServices(choicesFrom(value));
      })
      .catch(() => {
        if (!cancelled) setServices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [withChoice]);

  useEffect(() => {
    if (service === '') return;
    let cancelled = false;
    leadGet(`/api/bff/lead/reporters?service=${encodeURIComponent(service)}`)
      .then((value) => {
        if (!cancelled) setReading({ service, ending: endingOf(value) });
      })
      .catch(() => {
        if (!cancelled) setReading({ service, ending: null });
      });
    return () => {
      cancelled = true;
    };
  }, [service]);

  const currentEnding = reading?.service === service ? reading.ending : null;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setFailure(null);
    if (!isUkMobile(mobile)) {
      setMobileError('Enter a UK mobile number, like 07700 900456');
      return;
    }
    setMobileError(null);
    if (service === '' || until === null) {
      setFailure('Choose the service and how long the cover lasts.');
      return;
    }
    keyRef.current ??= newIdempotencyKey();
    setSaving(true);
    const result = await leadPost(
      '/api/bff/lead/reporters/number',
      { serviceId: service, newNumber: mobile, until },
      keyRef.current,
    );
    setSaving(false);
    if (!result.ok) {
      setFailure('The number could not be changed. Try again.');
      return;
    }
    keyRef.current = null;
    const ending = (result.body as { numberEnding?: unknown } | undefined)?.numberEnding;
    setSaved(true);
    onNotice(typeof ending === 'string' ? `New number ending ${ending} saved` : 'New number saved', false);
    if (typeof ending === 'string') setReading({ service, ending });
    setMobile('');
  }

  async function testText() {
    if (service === '') return;
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(service)}/test-prompt`);
    onNotice(result.ok ? 'Test text sent.' : 'The test text could not be sent.', !result.ok);
  }

  const fields = (
    <form onSubmit={(event) => void save(event)} noValidate id={panelId} className={styles.panel} hidden={withChoice ? false : !open}>
      {withChoice ? (
        <div className={styles.field}>
          <label htmlFor={serviceFieldId} className={styles.label}>
            Service
          </label>
          <select
            id={serviceFieldId}
            className={styles.input}
            value={service}
            onChange={(event) => setService(event.target.value)}
          >
            <option value="">Choose a service</option>
            {services.map((choice) => (
              <option key={choice.id} value={choice.id}>
                {choice.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {currentEnding !== null ? <p className={styles.muted}>{`Current number ends ${currentEnding}`}</p> : null}

      <div className={styles.field}>
        <label htmlFor={mobileId} className={styles.label}>
          New mobile number
        </label>
        {mobileError ? (
          <p role="alert" className={styles.error}>
            {mobileError}
          </p>
        ) : null}
        <input
          id={mobileId}
          className={styles.input}
          inputMode="tel"
          autoComplete="off"
          placeholder="07700 900456"
          value={mobile}
          onChange={(event) => setMobile(event.target.value)}
        />
      </div>

      <div role="group" aria-labelledby={groupId} className={styles.field}>
        <p id={groupId} className={styles.label}>
          How long?
        </p>
        <div className={styles.chips}>
          {COVERS.map(([value, text]) => (
            <Chip
              key={value}
              pressed={until === value}
              onPressedChange={() => setUntil(value)}
              dataEl={`LEAD-NUM-UNTIL-${value.toUpperCase()}`}
            >
              {text}
            </Chip>
          ))}
        </div>
      </div>

      <p className={styles.muted}>The old number stops working as soon as you save. Both numbers are logged.</p>

      {failure ? (
        <p role="alert" className={styles.error}>
          {failure}
        </p>
      ) : null}

      <div className={styles.buttons}>
        <Button variant="secondary" type="submit" busy={saving} dataEl="LEAD-NUM-SAVE-BTN">
          Send a new invitation
        </Button>
        <Button variant="secondary" disabled={!saved} onClick={() => void testText()} dataEl="LEAD-NUM-TEST-BTN">
          Send a test text
        </Button>
      </div>
    </form>
  );

  if (withChoice) {
    return (
      <section className={styles.card} aria-labelledby={`${panelId}-h`}>
        <h2 id={`${panelId}-h`} className={styles.cardHeading}>
          Change their number
        </h2>
        <p className={styles.muted}>The new number gets a fresh code. The old one stops working.</p>
        {fields}
      </section>
    );
  }

  return (
    <div className={styles.row}>
      <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>
        <span>Change their number</span>
        <svg className={styles.chevron} width="18" height="18" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
          <path d="M5 12l5-5 5 5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {fields}
    </div>
  );
}

export function ChangeNumberForm({ serviceId }: { serviceId?: string }) {
  const router = useRouter();
  const [items, setItems] = useState<Invitation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [now] = useState(() => Date.now());
  const [notice, setNotice] = useState<{ text: string; failed: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void leadRead('/api/bff/lead/invitations').then((result) => {
      if (cancelled) return;
      try {
        if (!result.ok) throw new Error('refused');
        setItems(invitationsFrom(result.body));
      } catch {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const onNotice = (text: string, isFailed: boolean) => setNotice({ text, failed: isFailed });
  const open = serviceId !== undefined ? (items?.find((item) => item.serviceId === serviceId) ?? null) : null;

  let list;
  if (failed) {
    list = (
      <div className={stageStyles.card} role="alert" data-tone="error">
        <h2 className={stageStyles.cardHeading}>
          <span aria-hidden="true">▲ </span>We could not load set-up progress
        </h2>
        <p className={stageStyles.cardText}>Nothing has been lost. You can still change the number.</p>
      </div>
    );
  } else if (items === null) {
    list = (
      <Loading label="Loading the set-up progress.">
        <SkeletonRows count={3} />
      </Loading>
    );
  } else {
    list = (
      <ReporterList
        items={items}
        now={now}
        currentId={open?.id ?? null}
        onOpen={(id) => router.push(`${REPORTERS}?invitation=${encodeURIComponent(id)}`)}
      />
    );
  }

  let detail;
  if (serviceId !== undefined && items === null && !failed) {
    detail = (
      <Loading label="Loading the reporter.">
        <SkeletonRows count={3} />
      </Loading>
    );
  } else if (open !== null && stuckAt(open.steps) !== null) {
    detail = (
      <ReporterDetail
        key={open.id}
        item={open}
        now={now}
        onBack={() => router.push(REPORTERS)}
        onNotice={onNotice}
        changeNumber={<NumberRow serviceId={open.serviceId} withChoice={false} onNotice={onNotice} />}
      />
    );
  } else {
    detail = <NumberRow serviceId={serviceId} withChoice onNotice={onNotice} />;
  }

  return (
    <main className={stageStyles.page}>
      <PageHeader title="Reporters" />
      <p role={notice?.failed ? 'alert' : 'status'} className={stageStyles.notice} data-failed={notice?.failed ?? false}>
        {notice?.text ?? ''}
      </p>
      <ReporterStage state="number" list={list} detail={detail} />
    </main>
  );
}
