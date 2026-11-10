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
// /advisor/v2/services/[id] (Advisor and Advisor v2). Laid out as the AQIKO Mark service detail: a breadcrumb and a back
// control; the name, group, districts and status; the capacity ("n / normal" with the places in use, or "Current
// capacity unavailable" with the last figure small when it is late or old, DEC-1343) beside the day chart, broken where
// the capacity was unknown; the reporting strip; the contact (the service's own number, opening hours, catchment) beside
// the referral criteria. Never a person's email or mobile, and nothing the system does not hold is invented: a missing
// number, hours or criteria are said to be missing.

const NO_PHONE = 'No phone number is held for this service. Find it in your service directory.';
const NO_CRITERIA = 'Not held. Phone the service to check.';

type Load = { kind: 'loading' } | { kind: 'ready'; detail: ServiceDetailView } | { kind: 'failed' };

export function ServiceDetail({
  serviceId,
  backHref,
  backLabel,
  rootLabel,
}: {
  serviceId: string;
  backHref: string;
  /** The back control's name, for example "Back to the overview". */
  backLabel: string;
  /** The first crumb, which links to `backHref`, for example "Capacity Board". */
  rootLabel: string;
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

  const area = load.kind === 'ready' ? catchmentText(load.detail.districts) : null;

  return (
    <div className={styles.page}>
      <div className={styles.crumbRow}>
        <nav aria-label="Breadcrumb">
          <ol className={styles.crumbs}>
            <li>
              <Link href={backHref}>{rootLabel}</Link>
            </li>
            {area === null ? null : <li>{area}</li>}
            <li aria-current="page">Service capacity</li>
          </ol>
        </nav>
        <Link href={backHref} className={styles.back}>
          <span aria-hidden="true">&larr;</span>
          {backLabel}
        </Link>
      </div>
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
  const current = !option.figureUnavailable && detail.effectiveAvailable !== null;
  const sub = [
    detail.category === null ? null : categoryLabel(detail.category),
    catchment === null ? null : detail.districts.join(' · '),
  ]
    .filter((part) => part !== null)
    .join(' · ');

  return (
    <>
      <section className={styles.head} aria-label="Service">
        <div className={styles.headText}>
          <h1 className={styles.name}>{detail.name}</h1>
          <p className={styles.sub}>{sub}</p>
        </div>
        <StatusBadge status={detail.status} />
      </section>

      <div className={styles.overview}>
        <section className={styles.panel} aria-labelledby="sd-capacity">
          <h2 id="sd-capacity" className={styles.panelHeading}>
            Capacity remaining
          </h2>
          {current ? (
            <>
              <p className={styles.fraction} aria-label={`${number} of ${detail.established} ${detail.unitLabel}`}>
                <strong>{number}</strong>
                <span>{`/ ${detail.established}`}</span>
              </p>
              <p className={styles.small}>
                {over ? `${detail.unitLabel}, above normal capacity` : `${detail.unitLabel} remaining of normal capacity`}
              </p>
              {detail.used === null ? null : <p className={styles.inUse}>{`${detail.used} ${detail.unitLabel} in use`}</p>}
            </>
          ) : (
            <>
              <p className={styles.unavailable}>Current capacity unavailable</p>
              <p className={styles.small}>{lastReportedLine(option)}</p>
              <p className={styles.small}>{`Normal capacity: ${detail.established} ${detail.unitLabel}`}</p>
            </>
          )}
        </section>
        <div className={styles.panel}>
          <DayChart serviceId={detail.serviceId} />
        </div>
      </div>

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
        <ContactPanel phone={detail.phone} hours={hours} catchment={catchment} />
        <section className={styles.panel} aria-label="Referral criteria">
          <h2 className={styles.panelHeading}>Referral criteria</h2>
          <h3 className={styles.subHeading}>Potentially accepts</h3>
          {acceptsLabels.length === 0 ? <p className={styles.note}>{NO_CRITERIA}</p> : <Chips labels={acceptsLabels} />}
          <hr className={styles.divider} />
          <h3 className={styles.subHeading}>Example exclusions</h3>
          {excludes === null ? (
            <p className={styles.note}>{NO_CRITERIA}</p>
          ) : excludes.length === 0 ? (
            <p className={styles.note}>None listed</p>
          ) : (
            <Chips labels={excludes} />
          )}
          <p className={styles.caveat}>
            The criteria are a guide. The receiving service confirms whether it can take the person.
          </p>
        </section>
      </div>
    </>
  );
}

function ContactPanel({ phone, hours, catchment }: { phone: string | null; hours: string[]; catchment: string | null }) {
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
      <h2 className={styles.panelHeading}>Service and contact</h2>
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
      <ul className={styles.meta} aria-label="Service details">
        <li className={styles.metaRow}>
          <span className={styles.metaLabel}>Opening hours</span>
          <span className={styles.metaValue}>
            {hours.length === 0 ? 'Not held.' : hours.map((line) => <span key={line}>{line}</span>)}
          </span>
        </li>
        <li className={styles.metaRow}>
          <span className={styles.metaLabel}>Catchment</span>
          <span className={styles.metaValue}>{catchment ?? 'Not held.'}</span>
        </li>
      </ul>
    </section>
  );
}
