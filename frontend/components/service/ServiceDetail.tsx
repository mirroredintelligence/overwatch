'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { DayChart } from '@/components/advisor/DayChart';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { bffFetch } from '@/lib/advisor/browser';
import { lastReportedLine, reportingStrip } from '@/lib/advisor/reporting';
import {
  ageText,
  catchmentText,
  criteriaLabels,
  detailAsOption,
  openingHoursLines,
  parseServiceDetail,
  type ServiceDetailView,
} from '@/lib/advisor/serviceDetail';
import { categoryLabel } from '@/lib/board/format';
import styles from './ServiceDetail.module.css';

// The one service detail page (DEC-1367), mounted at /analytics/services/[id] (Analytics User) and
// /advisor/v2/services/[id] (Advisor and Advisor v2). Its order: name, group, districts and status; the capacity as
// "n / normal", or "Current capacity unavailable" with the last figure small when it is late or old (DEC-1343); the
// day chart, broken where the capacity was unknown; the reporting strip; the contact, what it potentially accepts and
// excludes, and its catchment. Never a person's email or mobile, and nothing the system does not hold is invented: a
// missing number, hours or criteria are said to be missing.

const NO_PHONE = 'No phone number is held for this service. Find it in your service directory.';
const NO_CRITERIA = 'Not held. Phone the service to check.';

type Load = { kind: 'loading' } | { kind: 'ready'; detail: ServiceDetailView } | { kind: 'failed' };

export function ServiceDetail({
  serviceId,
  backHref,
  backLabel,
}: {
  serviceId: string;
  backHref: string;
  backLabel: string;
}) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let live = true;
    bffFetch<unknown>(`/api/bff/advisor/services/${encodeURIComponent(serviceId)}/detail`).then((reply) => {
      if (!live) return;
      if (!reply.ok) {
        setLoad({ kind: 'failed' });
        return;
      }
      try {
        setLoad({ kind: 'ready', detail: parseServiceDetail(reply.body) });
      } catch {
        setLoad({ kind: 'failed' });
      }
    });
    return () => {
      live = false;
    };
  }, [serviceId]);

  return (
    <div className={styles.page}>
      <Link href={backHref} className={styles.back}>
        {backLabel}
      </Link>
      {load.kind === 'loading' ? <p className={styles.note}>Loading the service.</p> : null}
      {load.kind === 'failed' ? <p className={styles.note}>The service could not be read.</p> : null}
      {load.kind === 'ready' ? <Ready detail={load.detail} /> : null}
    </div>
  );
}

function Chips({ labels }: { labels: string[] }) {
  return (
    <ul className={styles.chips}>
      {labels.map((label) => (
        <li key={label} className={styles.chip}>
          {label}
        </li>
      ))}
    </ul>
  );
}

function Ready({ detail }: { detail: ServiceDetailView }) {
  const option = detailAsOption(detail);
  const strip = reportingStrip(option);
  const hours = openingHoursLines(detail.openingHours);
  const accepts = criteriaLabels(detail.accepts);
  const excludes = criteriaLabels(detail.excludes);
  const age = ageText(detail.ageMin, detail.ageMax);
  const catchment = catchmentText(detail.districts);
  const over = detail.status === 'over-capacity' && detail.overBy !== null;
  const number = over ? `+${detail.overBy}` : String(detail.effectiveAvailable ?? '?');
  const acceptsLabels = [...(accepts ?? []), ...(age === null ? [] : [age])];

  return (
    <>
      <section className={styles.head} aria-label="Service">
        <h1 className={styles.name}>{detail.name}</h1>
        <p className={styles.sub}>
          {detail.category === null ? null : <span>{categoryLabel(detail.category)}</span>}
          {catchment === null ? null : <span>{detail.districts.join(' · ')}</span>}
          <StatusBadge status={detail.status} size="lg" />
        </p>
      </section>

      <section className={styles.panel} aria-labelledby="sd-capacity">
        <h2 id="sd-capacity" className={styles.panelHeading}>
          Capacity remaining
        </h2>
        {option.figureUnavailable || detail.effectiveAvailable === null ? (
          <>
            <p className={styles.unavailable}>Current capacity unavailable</p>
            <p className={styles.small}>{lastReportedLine(option)}</p>
            <p className={styles.small}>{`Normal capacity: ${detail.established} ${detail.unitLabel}`}</p>
          </>
        ) : (
          <>
            <p className={styles.fraction} aria-label={`${number} of ${detail.established} ${detail.unitLabel}`}>
              <strong>{number}</strong>
              <span>{`/ ${detail.established}`}</span>
            </p>
            <p className={styles.small}>
              {over ? `${detail.unitLabel}, above normal capacity` : `${detail.unitLabel} remaining of normal capacity`}
            </p>
          </>
        )}
      </section>

      <DayChart serviceId={detail.serviceId} />

      {strip === null ? null : (
        <section className={styles.panel} aria-label="Capacity reporting">
          <dl className={styles.strip}>
            <div className={styles.stripItem}>
              <dt>Last update</dt>
              <dd>{strip.lastUpdate}</dd>
            </div>
            <div className={styles.stripItem}>
              <dt>Frequency</dt>
              <dd>{strip.frequency}</dd>
            </div>
            <div className={styles.stripItem}>
              <dt>Next due</dt>
              <dd>{strip.nextDue}</dd>
            </div>
            <div className={styles.stripItem}>
              <dt>Schedule</dt>
              <dd className={strip.overdue ? styles.overdue : undefined}>{strip.schedule}</dd>
            </div>
          </dl>
        </section>
      )}

      <div className={styles.columns}>
        <ContactPanel phone={detail.phone} hours={hours} />
        <section className={styles.panel} aria-label="Potentially accepts">
          <h2 className={styles.panelHeading}>Potentially accepts</h2>
          {acceptsLabels.length === 0 ? <p className={styles.note}>{NO_CRITERIA}</p> : <Chips labels={acceptsLabels} />}
        </section>
        <section className={styles.panel} aria-label="Exclusions">
          <h2 className={styles.panelHeading}>Exclusions</h2>
          {excludes === null ? (
            <p className={styles.note}>{NO_CRITERIA}</p>
          ) : excludes.length === 0 ? (
            <p className={styles.note}>None listed</p>
          ) : (
            <Chips labels={excludes} />
          )}
        </section>
        <section className={styles.panel} aria-label="Catchment">
          <h2 className={styles.panelHeading}>Catchment</h2>
          <p className={styles.note}>{catchment ?? 'Not held.'}</p>
        </section>
      </div>
      <p className={styles.small}>The criteria are a guide. The receiving service confirms whether it can take the person.</p>
    </>
  );
}

function ContactPanel({ phone, hours }: { phone: string | null; hours: string[] }) {
  const [copied, setCopied] = useState(false);

  async function copy(number: string) {
    try {
      await navigator.clipboard.writeText(number);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className={styles.panel} aria-label="Contact">
      <h2 className={styles.panelHeading}>Contact</h2>
      {phone === null ? (
        <p className={styles.note}>{NO_PHONE}</p>
      ) : (
        <div className={styles.phoneRow}>
          <strong className={styles.phone}>{phone}</strong>
          <Button variant="secondary" onClick={() => void copy(phone)}>
            Copy number
          </Button>
          {copied ? (
            <span role="status" className={styles.small}>
              Number copied
            </span>
          ) : null}
        </div>
      )}
      <h3 className={styles.panelHeading}>Opening hours</h3>
      {hours.length === 0 ? (
        <p className={styles.note}>Not held.</p>
      ) : (
        <ul className={styles.lines}>
          {hours.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
