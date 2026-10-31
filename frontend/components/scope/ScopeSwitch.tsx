import styles from './Scope.module.css';

// The switch between the two route families (docs/design/network-ui.md section 3): the organisation's own
// pages and the network's. Two links, never a toggle and never a parameter: a change of scope is a
// navigation. The current one is marked with aria-current.

export type ScopeLinks = {
  /** The page of the viewer's own organisation that this page is the network variant of. */
  ownHref: string;
  /** The network variant of that page. */
  networkHref: string;
};

export function ScopeSwitch({ current, ownHref, networkHref }: ScopeLinks & { current: 'own' | 'network' }) {
  return (
    <nav className={styles.switch} aria-label="Choose the board">
      <a href={ownHref} className={styles.link} aria-current={current === 'own' ? 'page' : undefined} data-el="SCOPE-SWITCH-OWN-LINK">
        Our organisation
      </a>
      <a href={networkHref} className={styles.link} aria-current={current === 'network' ? 'page' : undefined} data-el="SCOPE-SWITCH-NETWORK-LINK">
        Network
      </a>
    </nav>
  );
}
