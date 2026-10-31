import styles from './Scope.module.css';
import { ScopeSwitch, type ScopeLinks } from './ScopeSwitch';

// The permanent scope header (docs/design/network-ui.md section 3, TEN-069): which board is on the page,
// in words, so a person never reads another organisation's figure as their own. It is part of the board
// component and not page chrome, so it appears on a wall that has no address bar, and it never goes away,
// including when the figures are last known or the network is not available.
//
// It takes the network's display name and nothing that identifies a tenant or a network. The switch is
// shown only when the viewer has a network to switch to (the page passes the two routes), and never on a
// wall, which is set by its administrator.

export type ScopeHeaderProps =
  | { scope: 'own'; networkName?: undefined; switchTo?: ScopeLinks; variant?: 'page' | 'wall' }
  | { scope: 'network'; networkName: string; switchTo?: ScopeLinks; variant?: 'page' | 'wall' };

export function ScopeHeader({ scope, networkName, switchTo, variant = 'page' }: ScopeHeaderProps) {
  const text = scope === 'own' ? 'Showing: Our organisation' : `Showing: Network, ${networkName}`;
  const wall = variant === 'wall';
  return (
    <section className={`${styles.header} ${wall ? styles.wall : ''}`} aria-label="Which board you are viewing" data-scope={scope}>
      <p className={styles.label} data-el="SCOPE-HEADER-LABEL">
        {text}
      </p>
      {switchTo !== undefined && !wall ? <ScopeSwitch current={scope} {...switchTo} /> : null}
    </section>
  );
}
