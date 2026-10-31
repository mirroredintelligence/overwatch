'use client';

import { useRouter } from 'next/navigation';
import styles from './map.module.css';

// Map and List, the two views of the same options (W50). Each is a button that says whether it is the
// view on screen; choosing the one already shown does nothing. The network's options (WB11) have the same
// two views of the same case, on their own two routes, with the same ids.

export function ViewToggle({ caseId, current, scope = 'own' }: { caseId: string; current: 'map' | 'list'; scope?: 'own' | 'network' }) {
  const router = useRouter();
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;
  const prefix = scope === 'network' ? 'network-' : '';

  function go(view: 'map' | 'list') {
    if (view === current) return;
    router.push(view === 'map' ? `${base}/${prefix}map` : `${base}/${prefix}options`);
  }

  return (
    <div className={styles.toggle} role="group" aria-label="View">
      <button
        type="button"
        className={styles.toggleButton}
        aria-pressed={current === 'map'}
        data-el="ADV-MAP-TOGGLE-MAP"
        onClick={() => go('map')}
      >
        Map
      </button>
      <button
        type="button"
        className={styles.toggleButton}
        aria-pressed={current === 'list'}
        data-el="ADV-MAP-TOGGLE-LIST"
        onClick={() => go('list')}
      >
        List
      </button>
    </div>
  );
}
