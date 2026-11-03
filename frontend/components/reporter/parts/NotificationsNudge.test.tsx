import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { NotificationsNudge } from './NotificationsNudge';

// The notifications-off strip (artboard B9, board 4). It reads only the browser's permission.

afterEach(() => vi.unstubAllGlobals());

describe('NotificationsNudge', () => {
  it('says notifications are off and links to the page that explains how to fix it', async () => {
    vi.stubGlobal('Notification', { permission: 'denied' });
    const { container } = render(<NotificationsNudge />);
    const strip = screen.getByRole('status');
    expect(strip).toHaveTextContent('Notifications are off.');
    expect(strip).toHaveTextContent('You may miss requests.');
    expect(screen.getByRole('link', { name: 'Fix this' })).toHaveAttribute('href', '/app/notifications-off');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('draws a picture that is hidden from a screen reader', () => {
    vi.stubGlobal('Notification', { permission: 'denied' });
    const { container } = render(<NotificationsNudge />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it.each(['granted', 'default'])('shows nothing when the permission is %s', (permission) => {
    vi.stubGlobal('Notification', { permission });
    const { container } = render(<NotificationsNudge />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows nothing where the browser has no notifications at all', () => {
    vi.stubGlobal('Notification', undefined);
    const { container } = render(<NotificationsNudge />);
    expect(container).toBeEmptyDOMElement();
  });
});
