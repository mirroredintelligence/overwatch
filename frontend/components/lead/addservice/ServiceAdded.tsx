'use client';

import { useEffect, useRef } from 'react';
import { Button } from '@/components/ui/Button';
import styles from './ServiceAdded.module.css';

// The state after the service is added (boards/lead/AddService.dc.html): a tick, "<name> is added", and the next
// action, which is to invite the reporter (the existing invite page, with the service chosen). The layer is only
// mounted once it is current, so focus goes to the heading when it appears.

export type ServiceAddedProps = {
  name: string;
  /** The id the back end answered with; without it the invite page opens with no service chosen. */
  serviceId: string | null;
  /** Whether the reporter was texted for the capacity figure as the service was saved. */
  invite?: 'sent' | 'failed' | 'none';
  onAddAnother: () => void;
};

export function ServiceAdded({ name, serviceId, invite: texted = 'none', onAddAnother }: ServiceAddedProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  const invite = serviceId === null ? '/lead/reporters/invite' : `/lead/reporters/invite?service=${encodeURIComponent(serviceId)}`;
  return (
    <div className={styles.card}>
      <div className={styles.tick} aria-hidden="true">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      </div>
      <h1 ref={heading} tabIndex={-1} data-morph-focus="" className={styles.heading}>
        {`${name} is added`}
      </h1>
      <p className={styles.text}>
        {texted === 'sent'
          ? 'The reporter has been texted and asked for the capacity figure. It shows on the board as soon as they reply.'
          : texted === 'failed'
            ? 'The text to the reporter could not be sent. Invite them below to ask for the capacity figure.'
            : 'It shows on the board as not yet reporting. Invite the reporter to set up reporting, so the first figure arrives today.'}
      </p>
      <div className={styles.actions}>
        <Button variant="primary" href={invite} dataEl="LEAD-ADD-INVITE-BTN">
          Invite the reporter
        </Button>
        <button type="button" className={styles.another} onClick={onAddAnother}>
          Add another service
        </button>
      </div>
    </div>
  );
}
