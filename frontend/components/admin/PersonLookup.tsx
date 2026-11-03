'use client';

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { bffRequest } from '@/lib/bff/browser';
import { Avatar } from './Avatar';
import styles from './People.module.css';

// Find a person in the organisation's own directory and add them to a role. Typing two letters of a name or an
// address searches the directory (the back end does it, for the administrator only); the matches are listed under
// the box, and choosing one adds that person. A person already in the role, or with no email address to add them
// by, is shown but cannot be chosen. The list is part of the page's flow, not a floating menu, so it is never
// clipped by the panel it is in. Nothing typed or found is kept anywhere but in this component.

export type Person = { userId: string; displayName: string | null; mail: string | null };

const MIN_LENGTH = 2;
const PAUSE_MS = 220;

type Status = 'idle' | 'searching' | 'done' | 'failed';

export function PersonLookup({
  label,
  memberIds,
  busy,
  onPick,
}: {
  label: string;
  memberIds: ReadonlySet<string>;
  busy: boolean;
  onPick: (person: Person) => void;
}) {
  const [query, setQuery] = useState('');
  // What the directory answered, and for which words: an answer for other words is not shown, so what is on
  // screen is always for what is in the box, and a slow answer to older words cannot replace it.
  const [answer, setAnswer] = useState<{ term: string; people: Person[]; failed: boolean } | null>(null);
  const [active, setActive] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const term = query.trim();
  const status: Status = term.length < MIN_LENGTH ? 'idle' : answer?.term !== term ? 'searching' : answer.failed ? 'failed' : 'done';
  const people = status === 'done' && answer !== null ? answer.people : [];

  useEffect(() => {
    if (term.length < MIN_LENGTH) return;
    let current = true;
    const timer = setTimeout(() => {
      void bffRequest<{ people: Person[] }>(`/api/bff/tenant/people?q=${encodeURIComponent(term)}`).then((result) => {
        if (!current) return;
        setAnswer(result.ok ? { term, people: result.data.people, failed: false } : { term, people: [], failed: true });
        setActive(-1);
      });
    }, PAUSE_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [term]);

  const choosable = (person: Person) => person.mail !== null && !memberIds.has(person.userId);

  function pick(person: Person) {
    if (busy || !choosable(person)) return;
    onPick(person);
    setQuery('');
    input.current?.focus();
  }

  function move(step: 1 | -1) {
    const open = people.map((person, index) => (choosable(person) ? index : -1)).filter((index) => index >= 0);
    if (open.length === 0) return;
    const at = open.indexOf(active);
    const next = at === -1 ? (step === 1 ? 0 : open.length - 1) : (at + step + open.length) % open.length;
    setActive(open[next]!);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      move(1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      move(-1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const only = people.filter(choosable);
      const person = people[active] ?? (only.length === 1 ? only[0] : undefined);
      if (person) pick(person);
    } else if (event.key === 'Escape') {
      setQuery('');
    }
  }

  const showList = term.length >= MIN_LENGTH && status !== 'idle';
  const optionId = (index: number) => `${listId}-${index}`;
  const found = people.length === 1 ? '1 person found.' : `${people.length} people found.`;

  return (
    <div className={styles.lookup}>
      <label className={styles.lookupLabel} htmlFor={`${listId}-input`}>
        {label}
      </label>
      <div className={styles.lookupBox}>
        <svg className={styles.lookupIcon} viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
          <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        <input
          ref={input}
          id={`${listId}-input`}
          className={styles.lookupInput}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? optionId(active) : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder="Start typing a name or email address"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
        />
        {status === 'searching' ? <span className={styles.spinner} aria-hidden="true" /> : null}
      </div>
      <p className={styles.srOnly} aria-live="polite" aria-atomic="true">
        {status === 'done' ? (people.length === 0 ? 'No one found.' : found) : ''}
      </p>
      <ul id={listId} role="listbox" aria-label={label} className={styles.results} hidden={!showList}>
        {status === 'failed' ? (
          <li className={styles.resultNote} role="presentation">
            The directory could not be searched. Try again in a minute.
          </li>
        ) : null}
        {status === 'done' && people.length === 0 ? (
          <li className={styles.resultNote} role="presentation">
            No one in your directory matches that. Check the spelling, or try their email address.
          </li>
        ) : null}
        {people.map((person, index) => {
          const member = memberIds.has(person.userId);
          const usable = choosable(person);
          return (
            <li
              key={person.userId}
              id={optionId(index)}
              role="option"
              aria-selected={index === active}
              aria-disabled={!usable}
              className={`${styles.result} ${index === active ? styles.resultActive : ''} ${usable ? '' : styles.resultOff}`}
              data-css={JSON.stringify({ animationDelay: `${Math.min(index, 6) * 28}ms` })}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(person)}
            >
              <Avatar id={person.userId} name={person.displayName} mail={person.mail} size="sm" />
              <span className={styles.resultText}>
                <span className={styles.resultName}>{person.displayName ?? person.mail ?? 'Unnamed person'}</span>
                <span className={styles.resultMail}>{person.mail ?? 'No email address'}</span>
              </span>
              {member ? <span className={styles.resultTag}>Already in this role</span> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
