'use client';

import { useSyncExternalStore } from 'react';
import styles from './NotificationsNudge.module.css';

// The strip above a page when the phone has blocked notifications (artboard B9, board 4): "Notifications are
// off. You may miss requests." and a link to the page that says how to turn them on. It needs only the
// browser's permission, nothing from the server. Where the browser has no notifications, or they are allowed
// or not yet asked for, it draws nothing. The server render draws nothing too (the permission is the phone's).

function subscribe(onChange: () => void): () => void {
  let status: PermissionStatus | null = null;
  let live = true;
  if (typeof navigator !== 'undefined' && navigator.permissions?.query) {
    navigator.permissions
      .query({ name: 'notifications' })
      .then((result) => {
        if (!live) return;
        status = result;
        status.addEventListener('change', onChange);
      })
      .catch(() => undefined);
  }
  return () => {
    live = false;
    status?.removeEventListener('change', onChange);
  };
}

const isOff = (): boolean => typeof Notification !== 'undefined' && Notification.permission === 'denied';

export function NotificationsNudge() {
  const off = useSyncExternalStore(subscribe, isOff, () => false);
  if (!off) return null;
  return (
    <div className={styles.nudge} role="status">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d="M6 17h12l-1.5-2V10a4.5 4.5 0 0 0-9 0v5zM10 20h4" />
        <path d="M3 3l18 18" />
      </svg>
      <p className={styles.words}>
        <strong>Notifications are off.</strong> You may miss requests.
      </p>
      <a className={styles.fix} href="/app/notifications-off">
        Fix this
      </a>
    </div>
  );
}
