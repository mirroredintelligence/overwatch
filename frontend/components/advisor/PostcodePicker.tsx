'use client';

import { type KeyboardEvent, useEffect, useRef, useState } from 'react';
import styles from './NeedsForm.module.css';

// The postcode field with its own list of suggestions (DEC-1332), drawn on the page rather than by the
// browser, so it looks like the rest of the form. It follows the combobox pattern: arrow keys move through
// the list, Enter picks, Escape closes. A pick is a postcode from the local file; the form decides what it does.

export type PostcodePickerProps = {
  id: string;
  listId: string;
  value: string;
  options: string[];
  invalid: boolean;
  describedBy?: string;
  dataEl: string;
  onType: (typed: string) => void;
  onPick: (postcode: string) => void;
  onBlur: () => void;
  /**
   * The compact list for a narrow, scrolling panel (the assistant thread): at most `COMPACT_MAX` rows in the flow of the
   * card, no list of its own to scroll, and a line saying to keep typing when there are more. Off by default: the form
   * pages keep the floating list.
   */
  compact?: boolean;
};

export const COMPACT_MAX = 5;

export function PostcodePicker(props: PostcodePickerProps) {
  const { id, listId, value, options: all, invalid, describedBy, dataEl, onType, onPick, onBlur, compact = false } = props;
  const options = compact ? all.slice(0, COMPACT_MAX) : all;
  const more = compact ? all.length - options.length : 0;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const shown = open && options.length > 0;
  const listRef = useRef<HTMLUListElement>(null);

  // In a scrolling panel the list opens below the field and may be out of sight: bring it into view (the compact list
  // only; the floating list of the form pages is already placed by the browser).
  useEffect(() => {
    if (compact && shown) listRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [compact, shown, options.length]);
  const optionId = (index: number) => `${id}-option-${index}`;

  function pick(postcode: string) {
    setOpen(false);
    setActive(-1);
    onPick(postcode);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      setOpen(false);
      setActive(-1);
      return;
    }
    if (!shown) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((current) => (current + 1) % options.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((current) => (current <= 0 ? options.length - 1 : current - 1));
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      pick(options[active] ?? value);
    }
  }

  return (
    <div className={styles.picker}>
      <input
        id={id}
        name="postcode"
        type="text"
        className={styles.input}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={shown}
        aria-controls={shown ? listId : undefined}
        aria-activedescendant={shown && active >= 0 ? optionId(active) : undefined}
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(event) => {
          setOpen(true);
          setActive(-1);
          onType(event.target.value);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => {
          setOpen(false);
          setActive(-1);
          onBlur();
        }}
        aria-invalid={invalid ? 'true' : undefined}
        aria-describedby={describedBy}
        data-el={dataEl}
      />
      {shown ? (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Postcodes"
          className={compact ? styles.listCompact : styles.list}
          data-el={`${dataEl}-LIST`}
        >
          {options.map((postcode, index) => (
            <li
              key={postcode}
              id={optionId(index)}
              role="option"
              aria-selected={index === active}
              className={`${compact ? styles.optionCompact : styles.option}${index === active ? ` ${styles.optionActive}` : ''}`}
              // The mouse press picks before the input loses focus, so the list stays open long enough to click.
              onMouseDown={(event) => {
                event.preventDefault();
                pick(postcode);
              }}
            >
              {postcode}
            </li>
          ))}
        </ul>
      ) : null}
      {shown && more > 0 ? <p className={styles.listNote}>{`${more} more. Keep typing to narrow the list.`}</p> : null}
    </div>
  );
}
