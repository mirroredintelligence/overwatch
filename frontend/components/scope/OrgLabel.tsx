import styles from './Scope.module.css';

// The organisation under a network row's service name (docs/design/network-ui.md section 3, TEN-069), in
// the caption size. A row of the viewer's own organisation also carries the words "Your organisation":
// text in a bordered label, never a status colour and never the only way to tell the rows apart.

export function OrgLabel({ name, own = false }: { name: string; own?: boolean }) {
  return (
    <p className={styles.org}>
      <span className={styles.orgName}>{name}</span>
      {own ? <span className={styles.own}>Your organisation</span> : null}
    </p>
  );
}
