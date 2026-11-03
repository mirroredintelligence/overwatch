'use client';

import { useId, useState } from 'react';
import styles from './InvitePreview.module.css';

// The text the invited person gets (INV-02; LI1 board): a bubble beside the form. It is a polite live region and
// the form hands it the service only when a field is left, so a screen reader hears one change, not one per key.
// On a phone the bubble is one line with a Show text disclosure; above that width it is always open.

export function InvitePreview({ service }: { service: string }) {
  const [open, setOpen] = useState(false);
  const bubbleId = useId();
  return (
    <aside aria-label="The text we send" className={styles.panel}>
      <h3 className={styles.kicker}>The text they get</h3>
      <div id={bubbleId} role="status" aria-live="polite" data-open={open} className={styles.bubble}>
        {`Overwatch: you are invited to report capacity for ${service || 'this service'}. Setting up takes about 3 minutes: [link to set up]. The link works for 48 hours.`}
      </div>
      <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={bubbleId} onClick={() => setOpen((was) => !was)}>
        {open ? 'Hide text' : 'Show text'}
      </button>
      <p className={styles.note}>The link is made when you send.</p>
      <p className={styles.pilot}>
        <strong>Only services in the pilot</strong> can be invited. Add one on the scope list first.
      </p>
    </aside>
  );
}
