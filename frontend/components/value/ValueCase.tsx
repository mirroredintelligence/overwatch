import Link from 'next/link';
import { LAUNCH_KIT, MEASURES, PROMISES, SAVINGS_RULES } from '@/lib/value/content';
import styles from './Value.module.css';

// Selling the value (ValueCase artboard): what is promised to each group, how it is proved, the rules for
// claiming a saving and the launch kit. A public page: it holds no person's data and no figure that depends
// on a session, and it states no saving (every target is "[to agree]" until the baseline is measured).

function Tick() {
  return (
    <svg width="22" height="22" viewBox="0 0 30 30" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={styles.tick}>
      <circle cx="15" cy="15" r="12" />
      <path d="M9.5 15.5l4 4 7-8" />
    </svg>
  );
}

export function ValueCase() {
  return (
    <main className={styles.page}>
      <header className={styles.bar}>
        <p className={styles.barTitle}>Selling the value</p>
        <p className={styles.barNote}>Fewer calls and meetings. Faster answers.</p>
      </header>

      <h1 className={styles.title}>What we promise, and how we prove it</h1>

      <div className={styles.cards}>
        {PROMISES.map((pledge) => (
          <section key={pledge.group} className={styles.card} aria-label={pledge.group}>
            <h2 className={styles.cardTitle}>{pledge.group}</h2>
            <ul className={styles.ticks}>
              {pledge.items.map((item) => (
                <li key={item}>
                  <Tick />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <section className={styles.card} aria-labelledby="value-measure-heading">
        <h2 id="value-measure-heading" className={styles.sectionTitle}>What we measure</h2>
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className={styles.srOnly}>What we measure to show the value</caption>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Baseline (before)</th>
                <th scope="col">From the tool (after)</th>
                <th scope="col">Target</th>
              </tr>
            </thead>
            <tbody>
              {MEASURES.map((row) => (
                <tr key={row.measure}>
                  <th scope="row">{row.measure}</th>
                  <td>{row.baseline}</td>
                  <td>{row.after}</td>
                  <td>{row.target}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={styles.cards}>
        <section className={styles.card} aria-labelledby="value-rules-heading">
          <h2 id="value-rules-heading" className={styles.cardTitle}>Rules for claiming savings</h2>
          <p className={styles.prose}>{SAVINGS_RULES}</p>
        </section>
        <section className={styles.card} aria-labelledby="value-kit-heading">
          <h2 id="value-kit-heading" className={styles.cardTitle}>Launch kit</h2>
          <ul className={styles.kit}>
            {LAUNCH_KIT.map((item) => (
              <li key={item.text}>{item.href !== undefined ? <Link href={item.href}>{item.text}</Link> : item.text}</li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
