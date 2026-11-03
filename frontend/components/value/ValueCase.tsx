'use client';

import Link from 'next/link';
import { useState } from 'react';
import { LAUNCH_KIT, MEASURES, PROMISES, SAVINGS_RULES, TARGET_PLACEHOLDER } from '@/lib/value/content';
import styles from './Value.module.css';

// Selling the value (ValueCase artboard): what is promised to each group, how it is proved, the rules for
// claiming a saving and the launch kit. A public page: it holds no person's data and no figure that depends
// on a session, and it states no saving (every target is "[to agree]" until the baseline is measured).
// The measures table shows the first three rows; the rest open from a disclosure, so the layout changes only
// because the reader chose it.

// The board shows three measures, then "3 more measures".
const SHOWN_MEASURES = 3;

export function ValueCase() {
  const [moreOpen, setMoreOpen] = useState(false);
  const hidden = MEASURES.length - SHOWN_MEASURES;
  const rows = moreOpen ? MEASURES : MEASURES.slice(0, SHOWN_MEASURES);

  return (
    <main className={styles.page}>
      <header className={styles.bar}>
        <span className={styles.mark}>
          <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true" focusable="false">
            <circle cx="13" cy="13" r="10" stroke="#fff" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="#fff" />
            <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
          </svg>
        </span>
        <span className={styles.brand}>Overwatch</span>
      </header>

      <h1 className={styles.title}>What we promise, and how we prove it</h1>

      <div className={styles.cards}>
        {PROMISES.map((pledge) => (
          <section key={pledge.group} className={styles.card} aria-label={pledge.group}>
            <h2 className={styles.cardTitle}>{pledge.group}</h2>
            <ul className={styles.ticks}>
              {pledge.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <section className={styles.card} aria-labelledby="value-measure-heading">
        <h2 id="value-measure-heading" className={styles.sectionTitle}>What we measure</h2>
        <div className={styles.scroll}>
          <table id="value-measure-table" className={styles.table}>
            <caption className={styles.srOnly}>What we measure to show the value</caption>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Before go-live</th>
                <th scope="col">After</th>
                <th scope="col">Target</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.measure}>
                  <th scope="row">{row.measure}</th>
                  <td>{row.baseline}</td>
                  <td>{row.after}</td>
                  <td>
                    <span className={row.target === TARGET_PLACEHOLDER ? styles.pending : undefined}>{row.target}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          type="button"
          className={styles.more}
          aria-expanded={moreOpen}
          aria-controls="value-measure-table"
          onClick={() => setMoreOpen((open) => !open)}
        >
          {hidden} more measures
          <svg className={styles.chevron} data-open={moreOpen} viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
            <path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        <div className={styles.foot}>
          <section className={styles.rules} aria-labelledby="value-rules-heading">
            <h3 id="value-rules-heading" className={styles.boxTitle}>Rules for claiming savings</h3>
            <p className={styles.prose}>{SAVINGS_RULES}</p>
          </section>
          <section className={styles.kitBox} aria-labelledby="value-kit-heading">
            <h3 id="value-kit-heading" className={styles.boxTitle}>Launch kit</h3>
            <ul className={styles.kit}>
              {LAUNCH_KIT.map((item) => (
                <li key={item.text}>{item.href !== undefined ? <Link href={item.href}>{item.text}</Link> : item.text}</li>
              ))}
            </ul>
          </section>
        </div>
      </section>
    </main>
  );
}
