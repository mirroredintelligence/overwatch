'use client';

import Link from 'next/link';
import { useEffect, useRef, type ReactNode } from 'react';
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

// The assistant's conversation with the person, in the workspace drawer. It reads as a chat: the assistant's words sit
// plain beside a small mark, the person's choices are filled bubbles on the right, the card and the suggested replies
// follow in the same scrolling thread, and the newest turn is kept in view. The bar at the foot is where a typed
// message would go: free text is off, so it is not a text box, only a note that the person answers with the options
// above. The links are next/link (a client navigation): a plain anchor reloads the page, which would wipe the
// provider's in-memory criteria and thread.
export function ThreadDrawer({ messages, summary, chips, card, onHide }: ThreadDrawerProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const lastId = messages.length > 0 ? messages[messages.length - 1].id : '';
  const summaryLine = summary?.line ?? '';
  const hasCard = Boolean(card);

  // Keep the newest turn in view, as a chat does. With a card showing, the newest turn is the question the card
  // answers, so scroll to the top of that question (the card follows it); otherwise scroll to the bottom.
  useEffect(() => {
    const element = scroller.current;
    if (element === null) return;
    const rows = element.querySelectorAll<HTMLElement>('[data-row]');
    const lastRow = rows.length > 0 ? rows[rows.length - 1] : null;
    element.scrollTop = hasCard && lastRow !== null ? Math.max(0, lastRow.offsetTop - 4) : element.scrollHeight;
  }, [lastId, messages.length, summaryLine, chips.length, hasCard]);

  return (
    <div className={styles.drawer} data-el="WS-THREAD-DRAWER">
      <div className={styles.head}>
        <h2 className={styles.title}>Assistant</h2>
        <button type="button" className={styles.hide} aria-label="Hide the assistant" onClick={onHide}>
          Hide
        </button>
      </div>

      <div ref={scroller} className={styles.scroll}>
        <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" className={styles.log}>
          {messages.map((message) => (
            <div
              key={message.id}
              data-row
              className={`${styles.row} ${message.from === 'assistant' ? styles.rowAssistant : styles.rowPerson}`}
            >
              {message.from === 'assistant' ? (
                <span className={styles.avatar} aria-hidden="true">
                  ✦
                </span>
              ) : null}
              <p
                data-from={message.from}
                className={`${styles.message} ${message.from === 'assistant' ? styles.messageAssistant : styles.messagePerson}`}
              >
                {message.text}
              </p>
            </div>
          ))}
        </div>

        {summary ? (
          <div className={styles.summary}>
            <p className={styles.summaryLabel}>Criteria set</p>
            <p className={styles.summaryLine}>{summary.line}</p>
            <Link href={summary.changeHref}>Change criteria</Link>
          </div>
        ) : null}

        {card ? <div className={styles.cardSlot}>{card}</div> : null}

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
      </div>

      <p className={styles.composer}>
        <span>Pick an option above</span>
        <span className={styles.send} aria-hidden="true">
          ↑
        </span>
      </p>
    </div>
  );
}
