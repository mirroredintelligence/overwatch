import type { TenantProfile } from '@/lib/tenant/profile';
import styles from './TenantHeader.module.css';

// The organisation's own name at the top of a page, so a person who works for more than one
// organisation always sees which one this is. It shows the display name from the profile and nothing
// else: no id, no host, no network, no phone. Renders nothing when there is no profile (an unknown
// host, a back end that is down): the page then carries the product's own name alone.

export function TenantHeader({ profile }: { profile: TenantProfile | null }) {
  if (profile === null) return null;
  return (
    <section className={styles.header} aria-label="Organisation" data-el="TENANT-HEADER">
      <p className={styles.name}>{profile.displayName}</p>
    </section>
  );
}
