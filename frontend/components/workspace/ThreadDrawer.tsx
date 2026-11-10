import Link from 'next/link';
import type { ReactNode } from 'react';
import styles from './Thread.module.css';

export type ThreadMessage = { id: string; from: 'assistant' | 'person'; text: string };
export type ThreadChip = { label: string; href: string };
export type ThreadSummary = { line: string; changeHref: string };
export type ThreadDrawerProps = {
  messages: readonly ThreadMessage[];
  summary?: ThreadSummary | null;
  chips: readonly ThreadChip[];
  card?: ReactNode;
  onHide: () => void;
};

// The assistant's conversation with the person, in the workspace drawer. Free text is off: the person answers
// with the chips, the card or the criteria link, so there is no text box here. The links are next/link (a client
// navigation): a plain anchor reloads the page, which would wipe the provider's in-memory criteria and thread.
export function ThreadDrawer({ messages, summary, chips, card, onHide }: ThreadDrawerProps) {
  return (
    <div className={styles.drawer} data-el="WS-THREAD-DRAWER">
      <div className={styles.head}>
        <h2 className={styles.title}>Assistant</h2>
        <button type="button" className={styles.hide} aria-label="Hide the assistant" onClick={onHide}>
          Hide
        </button>
      </div>

      <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" className={styles.log}>
        {messages.map((message) => (
          <p
            key={message.id}
            data-from={message.from}
            className={`${styles.message} ${message.from === 'assistant' ? styles.messageAssistant : styles.messagePerson}`}
          >
            {message.text}
          </p>
        ))}
      </div>

      {summary ? (
        <div className={styles.summary}>
          <p className={styles.summaryLabel}>Criteria set</p>
          <p className={styles.summaryLine}>{summary.line}</p>
          <Link href={summary.changeHref}>Change criteria</Link>
        </div>
      ) : null}

      {card}

      {chips.length > 0 ? (
        <ul aria-label="Suggested replies" className={styles.chips}>
          {chips.map((chip) => (
            <li key={`${chip.label}|${chip.href}`}>
              <Link href={chip.href} className={styles.chip}>
                {chip.label}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

      <p className={styles.hint}>Pick an option above</p>
    </div>
  );
}
