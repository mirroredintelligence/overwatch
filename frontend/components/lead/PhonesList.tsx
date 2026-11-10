'use client';

import { useEffect, useId, useState } from 'react';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import { PageHeader } from '@/components/shell/PageHeader';
import { ConfirmDialog } from '@/components/blocks/ConfirmDialog';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { leadPost, leadRead } from '@/lib/lead/browser';
import { listOf, textOf } from '@/lib/lead/answers';
import { agoText } from '@/lib/lead/format';
import styles from './PhonesList.module.css';

// The phones the services report from, and the services on each (W43). A phone is shown by its last digits only.
// A phone that holds more than three services is flagged, since more than three services on one phone slows replies.
// Each phone is a row; a row opens (a disclosure) to show its services and what can be done with each.

export type PhoneRow = {
  phoneEnding: string;
  role: string;
  services: { id: string; name: string }[];
  channel: string;
  lastSeen: string;
};

const FLAG_ABOVE = 3;

function phonesFrom(body: unknown): PhoneRow[] {
  return listOf(body, 'phones').map((item) => {
    const row = item as Record<string, unknown>;
    return {
      phoneEnding: textOf(row.phoneEnding),
      role: textOf(row.role),
      services: listOf(row, 'services').map((s) => {
        const service = s as Record<string, unknown>;
        return { id: textOf(service.id), name: textOf(service.name) };
      }),
      channel: textOf(row.channel),
      lastSeen: textOf(row.lastSeen),
    };
  });
}

function capitalised(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function lastSeenText(lastSeen: string, now: number): string {
  if (lastSeen === '' || Number.isNaN(Date.parse(lastSeen))) return 'Not known';
  return agoText(lastSeen, now);
}

function isFlagged(phone: PhoneRow): boolean {
  return phone.services.length > FLAG_ABOVE;
}

function PhoneItem({ phone, now, onRetired }: { phone: PhoneRow; now: number; onRetired: (serviceId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [retiring, setRetiring] = useState<{ id: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | undefined>(undefined);

  async function retire() {
    if (retiring === null || busy) return;
    setBusy(true);
    setFailure(undefined);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(retiring.id)}/retire`);
    setBusy(false);
    if (!result.ok) {
      setFailure(result.status === 403 ? 'You cannot retire a service.' : 'The service could not be retired. Try again.');
      return;
    }
    const id = retiring.id;
    setRetiring(null);
    onRetired(id);
  }

  const panelId = useId();
  const flagged = isFlagged(phone);
  return (
    <li className={styles.row}>
      <h2 className={styles.heading}>
        <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}>
          <span className={styles.number}>{`···${phone.phoneEnding}`}</span>
          <span className={styles.roleWrap}>
            <span className={styles.role}>{phone.role}</span>
            <span className={styles.services}>{phone.services.map((s) => s.name).join(', ')}</span>
          </span>
          <span className={styles.channel}>{capitalised(phone.channel)}</span>
          <span className={styles.seen}>{lastSeenText(phone.lastSeen, now)}</span>
          {flagged ? (
            <span className={styles.flag}>
              <span className={styles.diamond} aria-hidden="true" />
              {`Holds ${phone.services.length} services. More than ${FLAG_ABOVE} slows replies.`}
            </span>
          ) : (
            <span className={styles.noFlag}>None</span>
          )}
          <svg className={styles.chevron} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
            <path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </h2>
      <div id={panelId} className={styles.panel} data-open={open} inert={!open}>
        <div className={styles.panelInner}>
          <div className={styles.panelBody}>
            {phone.services.map((s) => {
              const service = encodeURIComponent(s.id);
              return (
                <section key={s.id} className={styles.service}>
                  <h3 className={styles.serviceName}>{s.name}</h3>
                  <div className={styles.serviceActions}>
                    <Button variant="secondary" href={`/lead/reporters/number?service=${service}`} dataEl="LEAD-PHONES-NUMBER-BTN">
                      Change number
                    </Button>
                    <Button variant="secondary" href={`/lead/phones/move?service=${service}`} dataEl="LEAD-PHONES-SERVICE-MOVE-BTN">
                      Move this service
                    </Button>
                    <Button variant="neutral" href={`/lead/coverage/${service}`} dataEl="LEAD-PHONES-COVERAGE-BTN">
                      Edit the coverage area
                    </Button>
                    <Button
                      variant="neutral"
                      ariaLabel={`Retire ${s.name}`}
                      onClick={() => {
                        setFailure(undefined);
                        setRetiring({ id: s.id, name: s.name });
                      }}
                      dataEl="LEAD-PHONES-RETIRE-BTN"
                    >
                      Retire this service
                    </Button>
                  </div>
                </section>
              );
            })}
            <div className={styles.removeRow}>
              <Button
                variant="neutral"
                href={`/lead/people/remove?person=${encodeURIComponent(phone.phoneEnding)}`}
                dataEl="LEAD-PHONES-REMOVE-BTN"
              >
                Remove access
              </Button>
            </div>
          </div>
        </div>
      </div>
      {retiring === null ? null : (
        <ConfirmDialog
          title={`Retire ${retiring.name}?`}
          confirmLabel="Retire service"
          cancelLabel="Keep service"
          busy={busy}
          error={failure}
          onConfirm={() => void retire()}
          onCancel={() => setRetiring(null)}
          dataEl="LEAD-PHONES-RETIRE-CONFIRM"
        >
          <p>It leaves the board, the options and this list, and any open requests to it expire. Its past reports and requests stay in the record.</p>
          <p>This cannot be undone here. To pause it for a while instead, suspend it.</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

export function PhonesList() {
  const [phones, setPhones] = useState<PhoneRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    void leadRead('/api/bff/lead/phones').then((result) => {
      if (cancelled) return;
      try {
        if (!result.ok) throw new Error('refused');
        setPhones(phonesFrom(result.body));
      } catch {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function retired(serviceId: string) {
    setPhones((current) =>
      current === null
        ? current
        : current
            .map((phone) => ({ ...phone, services: phone.services.filter((s) => s.id !== serviceId) }))
            .filter((phone) => phone.services.length > 0),
    );
  }

  const serviceCount = phones?.reduce((total, phone) => total + phone.services.length, 0) ?? 0;
  const flaggedCount = phones?.filter(isFlagged).length ?? 0;
  const flagWords = flaggedCount === 0 ? '' : flaggedCount === 1 ? ' One has a flag.' : ` ${flaggedCount} have a flag.`;

  return (
    <main className={styles.page}>
      <PageHeader title="Phones and services" />
      {/* Which board this is (TEN-069), with the way to the network's phones when there is one (W43). */}
      <OwnScopeHeader ownHref="/lead/phones" networkHref="/network/phones" />

      <div className={styles.toolbar}>
        {phones !== null && phones.length > 0 ? (
          <p className={styles.summary}>
            {`${phones.length} ${phones.length === 1 ? 'phone' : 'phones'} hold ${serviceCount} ${serviceCount === 1 ? 'service' : 'services'}.${flagWords}`}
          </p>
        ) : (
          <span className={styles.summary} />
        )}
        <div className={styles.actions}>
          <Button variant="secondary" href="/lead/services/new" dataEl="LEAD-PHONES-ADD-BTN">
            Add a service
          </Button>
          <Button variant="primary" href="/lead/phones/move" dataEl="LEAD-PHONES-MOVE-BTN">
            Move a service
          </Button>
        </div>
      </div>

      <div className={styles.card}>
        {failed ? (
          <p role="alert" className={styles.error}>
            We could not load the phones.
          </p>
        ) : null}

        {!failed && phones === null ? (
          <Loading label="Loading the phones.">
            <SkeletonRows count={3} />
          </Loading>
        ) : null}

        {phones !== null && phones.length === 0 ? <p className={styles.muted}>No phone holds a service yet.</p> : null}

        {phones !== null && phones.length > 0 ? (
          <>
            <div className={styles.header} aria-hidden="true">
              <span>Phone</span>
              <span>Role and services</span>
              <span>Channel</span>
              <span>Last seen</span>
              <span>Flag</span>
              <span />
            </div>
            <ul className={styles.list} aria-label="Phones and the services they report for">
              {phones.map((phone) => (
                <PhoneItem key={phone.phoneEnding} phone={phone} now={now} onRetired={retired} />
              ))}
            </ul>
          </>
        ) : null}
      </div>

      <p className={styles.note}>Only the last four digits of a number are shown. A row opens to show what is on the phone and what you can do with it.</p>
    </main>
  );
}
