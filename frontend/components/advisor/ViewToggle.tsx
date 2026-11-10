'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import styles from './ViewToggle.module.css';

// The one segmented control over the options of a case (W50; advisor-clinical-wall.md, "Segmented control"):
// List, Compare, Map, Ways and Other organisations, each a link to its existing route, the one on
// screen marked aria-current="page". The network's options (WB11) are one tab, Other organisations; inside
// it the list and the map of the same case are two buttons on their own two routes, with the same ids.

export type OptionsView = 'list' | 'compare' | 'map' | 'ways';

const TABS: readonly { view: OptionsView | 'network'; label: string; path: string; el?: string }[] = [
  { view: 'list', label: 'List', path: 'options', el: 'ADV-MAP-TOGGLE-LIST' },
  { view: 'compare', label: 'Compare', path: 'compare' },
  { view: 'map', label: 'Map', path: 'map', el: 'ADV-MAP-TOGGLE-MAP' },
  { view: 'ways', label: 'Ways', path: 'ways' },
  { view: 'network', label: 'Other organisations', path: 'network-options' },
];

export function ViewToggle({
  caseId,
  current,
  scope = 'own',
}: {
  caseId: string;
  current: OptionsView;
  scope?: 'own' | 'network';
}) {
  const router = useRouter();
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;
  const network = scope === 'network';

  function go(view: 'map' | 'list') {
    if (view === current) return;
    router.push(`${base}/${view === 'map' ? 'network-map' : 'network-options'}`);
  }

  return (
    <div className={styles.wrap}>
      <nav className={styles.control} aria-label="Options view">
        {TABS.map((tab) => {
          const here = network ? tab.view === 'network' : tab.view === current;
          return (
            <Link
              key={tab.view}
              href={`${base}/${tab.path}`}
              className={styles.tab}
              aria-current={here ? 'page' : undefined}
              data-el={network ? undefined : tab.el}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {network ? (
        <div className={styles.sub} role="group" aria-label="Other organisations view">
          <button
            type="button"
            className={styles.subButton}
            aria-pressed={current === 'map'}
            data-el="ADV-MAP-TOGGLE-MAP"
            onClick={() => go('map')}
          >
            Map
          </button>
          <button
            type="button"
            className={styles.subButton}
            aria-pressed={current === 'list'}
            data-el="ADV-MAP-TOGGLE-LIST"
            onClick={() => go('list')}
          >
            List
          </button>
        </div>
      ) : null}
    </div>
  );
}
