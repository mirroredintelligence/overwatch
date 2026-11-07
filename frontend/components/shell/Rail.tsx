'use client';

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { usePathname } from 'next/navigation';
import { itemIsCurrent, type FrameItem } from './frame';
import { Icon } from './icons';
import styles from './AppFrame.module.css';

// The rail (artboard Rail.dc.html): an 84px dark column with the mark, the portal's items as icon over label,
// the current one a pale pill (aria-current in the markup, never colour alone: the pill is also bold), and
// Help pinned at the bottom. Below 900px it is a bottom bar: at most five entries, the fifth being "More",
// a native disclosure that holds the rest (Help last). The width is read with matchMedia; before it is known
// (the server's render) the rail is drawn, and the stylesheet already lays either out as a bar when narrow.

const NARROW = '(max-width: 899.98px)';
const HELP: FrameItem = { label: 'Help', href: '/help', icon: 'help' };
const BAR_DIRECT = 4;

function subscribe(onChange: () => void): () => void {
  const query = typeof window.matchMedia === 'function' ? window.matchMedia(NARROW) : null;
  query?.addEventListener('change', onChange);
  return () => query?.removeEventListener('change', onChange);
}
const isNarrow = (): boolean => (typeof window.matchMedia === 'function' ? window.matchMedia(NARROW).matches : false);

function RailLink({ item, current }: { item: FrameItem; current: boolean }) {
  return (
    <a className={styles.item} href={item.href} aria-current={current ? 'page' : undefined}>
      <Icon name={item.icon} />
      <span>{item.label}</span>
    </a>
  );
}

function More({ entries, pathname }: { entries: readonly FrameItem[]; pathname: string }) {
  const box = useRef<HTMLDetailsElement>(null);
  const active = entries.some((item) => itemIsCurrent(pathname, item));

  useEffect(() => {
    const close = () => {
      if (box.current?.open) box.current.open = false;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || !box.current?.open) return;
      close();
      box.current.querySelector('summary')?.focus();
    };
    const onPointer = (event: PointerEvent) => {
      if (box.current?.open && event.target instanceof Node && !box.current.contains(event.target)) close();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, []);

  return (
    <details ref={box} className={styles.more}>
      <summary className={styles.item} data-active={active ? 'true' : undefined}>
        <Icon name="more" />
        <span>More</span>
      </summary>
      <ul className={styles.morePanel}>
        {entries.map((item) => (
          <li key={item.href}>
            <RailLink item={item} current={itemIsCurrent(pathname, item)} />
          </li>
        ))}
      </ul>
    </details>
  );
}

export function Rail({ items, navLabel, homeHref }: { items: readonly FrameItem[]; navLabel: string; homeHref: string }) {
  const pathname = usePathname() ?? '';
  const narrow = useSyncExternalStore(subscribe, isNarrow, () => false);

  const mark = (
    <a className={styles.mark} href={homeHref} aria-label="Overwatch home">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
        <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
        <circle cx="13" cy="13" r="4.2" fill="#fff" />
        <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
      </svg>
    </a>
  );

  if (!narrow || items.length === 0) {
    return (
      <div className={styles.rail} data-noprint data-el="RAIL" data-layout={narrow ? 'bar' : 'rail'}>
        {mark}
        {items.length > 0 ? (
          <nav className={styles.nav} aria-label={navLabel}>
            <ul className={styles.list}>
              {items.map((item) => (
                <li key={item.href}>
                  <RailLink item={item} current={itemIsCurrent(pathname, item)} />
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
        <div className={styles.help}>
          <RailLink item={HELP} current={false} />
        </div>
      </div>
    );
  }

  const entries = [...items, HELP];
  const direct = entries.length <= 5 ? entries : entries.slice(0, BAR_DIRECT);
  const rest = entries.length <= 5 ? [] : entries.slice(BAR_DIRECT);
  return (
    <div className={styles.rail} data-noprint data-el="RAIL" data-layout="bar">
      {mark}
      <nav className={styles.nav} aria-label={navLabel}>
        <ul className={styles.list}>
          {direct.map((item) => (
            <li key={item.href}>
              <RailLink item={item} current={itemIsCurrent(pathname, item)} />
            </li>
          ))}
          {rest.length > 0 ? (
            <li>
              <More entries={rest} pathname={pathname} />
            </li>
          ) : null}
        </ul>
      </nav>
    </div>
  );
}
