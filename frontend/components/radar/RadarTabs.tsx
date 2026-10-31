import styles from './radar.module.css';

// The three views of the radar for one case, and the way back to the map and the list (RadarWeb 1, 2, 6).
// Plain links: each view is its own address, so the back button and a reload do what a person expects.

export type RadarView = 'radar' | 'compare' | 'ways';

const VIEWS: readonly { id: RadarView; label: string; path: string }[] = [
  { id: 'radar', label: 'Who covers', path: 'radar' },
  { id: 'compare', label: 'Compare', path: 'compare' },
  { id: 'ways', label: 'Three ways', path: 'ways' },
];

export function RadarTabs({ caseId, current }: { caseId: string; current: RadarView }) {
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;
  return (
    <nav aria-label="Radar views" className={styles.tabs}>
      {VIEWS.map((view) => (
        <a
          key={view.id}
          href={`${base}/${view.path}`}
          className={styles.tab}
          aria-current={view.id === current ? 'page' : undefined}
          data-el={`RADAR-TAB-${view.id.toUpperCase()}`}
        >
          {view.label}
        </a>
      ))}
      <a href={`${base}/map`} className={styles.tab} data-el="RADAR-TAB-MAP">
        Back to the map
      </a>
    </nav>
  );
}
