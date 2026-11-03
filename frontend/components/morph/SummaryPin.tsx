'use client';

import { useEffect, useRef, useState } from 'react';
import styles from './SummaryPin.module.css';

// The "So far" card of a guided flow (boards/lead/AddService.dc.html): what has been entered, as a read-only list,
// each part with a Change link. The card is a fixed width inside a column the page animates from 0 (the page's
// StageGrid template), so the text never reflows while the column grows; the card fades in over it. On a phone
// the same list is a one-line pill that opens a sheet (`variant="pill"`).

export type SummaryItem = {
  key: string;
  /** Small heading, for example "Who reports". */
  label: string;
  /** The answer, in words. */
  value: string;
  /** A second line, optional. */
  detail?: string;
  /** Where Change goes, when the step has an address. Without it Change is a button calling `onChange(key)`. */
  href?: string;
};

export type SummaryPinProps = {
  items: readonly SummaryItem[];
  /** Pressed on an item's Change (an item with an `href` is a link instead). Without either, no Change control. */
  onChange?: (key: string) => void;
  /** Card only: false while the column is closed (inert, hidden, faded). Default true. */
  open?: boolean;
  /** `card` is the left column, `pill` is the phone's one line. */
  variant?: 'card' | 'pill';
  /** The heading of the card and the lead of the pill. Default "So far". */
  title?: string;
  /** The accessible name of the region and of the sheet. Default "What you have entered". */
  label?: string;
};

function List({ items, onChange, onPick }: { items: readonly SummaryItem[]; onChange?: (key: string) => void; onPick?: () => void }) {
  return (
    <ul className={styles.list}>
      {items.map((item) => {
        const name = `Change ${item.label.charAt(0).toLowerCase()}${item.label.slice(1)}`;
        return (
          <li key={item.key} className={styles.item}>
            <div className={styles.key}>{item.label}</div>
            <div className={styles.value}>{item.value}</div>
            {item.detail ? <div className={styles.detail}>{item.detail}</div> : null}
            {item.href ? (
              <a className={styles.change} href={item.href} aria-label={name} onClick={onPick}>
                Change
              </a>
            ) : onChange ? (
              <button
                type="button"
                className={styles.change}
                aria-label={name}
                onClick={() => {
                  onChange(item.key);
                  onPick?.();
                }}
              >
                Change
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function SummaryPin({ items, onChange, open = true, variant = 'card', title = 'So far', label = 'What you have entered' }: SummaryPinProps) {
  const [sheet, setSheet] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const pillRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (sheet) closeRef.current?.focus();
    else if (wasOpen.current) pillRef.current?.focus();
    wasOpen.current = sheet;
  }, [sheet]);

  if (variant === 'pill') {
    if (items.length === 0) return null;
    const latest = items[items.length - 1];
    const count = `${items.length} ${items.length === 1 ? 'answer' : 'answers'}`;
    return (
      <div className={styles.pillWrap}>
        <button type="button" ref={pillRef} className={styles.pill} aria-expanded={sheet} onClick={() => setSheet(!sheet)}>
          <span className={styles.sr}>{`${title}, ${count}: ${latest.value}`}</span>
          <span className={styles.pillTitle} aria-hidden="true">
            {title}
          </span>
          <span className={styles.pillValue} aria-hidden="true">
            {latest.value}
          </span>
          <span className={styles.chev} aria-hidden="true" data-open={sheet}>
            <svg width="16" height="16" viewBox="0 0 20 20">
              <path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        </button>
        {sheet ? (
          <div
            className={styles.sheet}
            role="dialog"
            aria-label={label}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setSheet(false);
            }}
          >
            <div className={styles.sheetHead}>
              <div className={styles.k}>{title}</div>
              <button type="button" ref={closeRef} className={styles.close} onClick={() => setSheet(false)}>
                Close
              </button>
            </div>
            <List items={items} onChange={onChange} onPick={() => setSheet(false)} />
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <section
      aria-label={label}
      className={styles.pin}
      data-pin=""
      data-open={open ? 'true' : 'false'}
      inert={!open}
      aria-hidden={open ? undefined : true}
    >
      <div className={styles.card}>
        <div className={styles.k}>{title}</div>
        <List items={items} onChange={onChange} />
      </div>
    </section>
  );
}
