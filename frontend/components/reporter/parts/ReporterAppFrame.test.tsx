import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

const path = vi.hoisted(() => ({ current: '/app/services' }));
vi.mock('next/navigation', () => ({ usePathname: () => path.current }));

import { ReporterAppFrame } from './ReporterAppFrame';

// The installed app's frame (artboards B6, B9): a dark top bar with the mark, the page, and a bottom TabBar
// that is hidden on the PIN, verify, locked, lost-phone and practitioner pages.

function frame(pathname: string) {
  path.current = pathname;
  return render(
    <ReporterAppFrame>
      <main>
        <h1>The page</h1>
      </main>
    </ReporterAppFrame>,
  );
}

afterEach(() => {
  path.current = '/app/services';
  vi.unstubAllGlobals();
});

describe('ReporterAppFrame', () => {
  it('draws the top bar with the product name, the page, and the tab bar', async () => {
    const { container } = frame('/app/services');
    expect(screen.getByRole('banner')).toHaveTextContent('Overwatch');
    expect(screen.getByRole('heading', { name: 'The page' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'App' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('draws the page between the top bar and the tab bar', () => {
    frame('/app/settings');
    const bar = screen.getByRole('banner');
    const page = screen.getByRole('main');
    const tabs = screen.getByRole('navigation', { name: 'App' });
    expect(bar.compareDocumentPosition(page) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(page.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    '/app/pin',
    '/app/verify',
    '/app/locked',
    '/app/lost-phone',
    '/app/sign-out-all',
    '/app/notifications-off',
    '/app/practitioner',
    '/app/practitioner/round',
    '/app/practitioner/offers/o1',
  ])('hides the tab bar on %s but keeps the top bar and the page', (pathname) => {
    frame(pathname);
    expect(screen.queryByRole('navigation', { name: 'App' })).toBeNull();
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The page' })).toBeInTheDocument();
  });

  it('keeps the tab bar on a page whose name only starts like a hidden one', () => {
    frame('/app/pinned-things');
    expect(screen.getByRole('navigation', { name: 'App' })).toBeInTheDocument();
  });

  it('says so above the page when notifications are blocked, with a way to fix it', () => {
    vi.stubGlobal('Notification', { permission: 'denied' });
    frame('/app/respond/svc-1');
    expect(screen.getByRole('link', { name: 'Fix this' })).toHaveAttribute('href', '/app/notifications-off');
  });

  it('says nothing about notifications when they are allowed', () => {
    vi.stubGlobal('Notification', { permission: 'granted' });
    frame('/app/respond/svc-1');
    expect(screen.queryByRole('link', { name: 'Fix this' })).toBeNull();
  });
});
