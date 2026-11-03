import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

const state = vi.hoisted(() => ({ path: '/console' }));

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation');
  return { ...actual, usePathname: () => state.path };
});

import ConsoleLayout from './layout';

// The support console's frame: the same rail and top bar as every other signed-in area, with the console's two
// places (the page itself checks that the session is a support session).

function layout() {
  return render(
    <ConsoleLayout>
      <p>The page</p>
    </ConsoleLayout>,
  );
}

describe('the console layout', () => {
  it('draws the frame around the page, with the console in the top bar and the role named Support', () => {
    state.path = '/console';
    layout();
    const bar = screen.getByRole('banner');
    expect(within(bar).getByText('Support console')).toBeInTheDocument();
    expect(within(bar).getByText('Support')).toBeInTheDocument();
    expect(screen.getByText('The page')).toBeInTheDocument();
  });

  it('has Sessions and Insight in the rail, and marks the one the person is on', () => {
    state.path = '/console/insight';
    layout();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Insight' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Sessions' })).not.toHaveAttribute('aria-current');
  });

  it('keeps Sessions current on a session and on a trace, which have no item of their own', () => {
    for (const path of ['/console/session/abc', '/console/trace/xyz']) {
      state.path = path;
      const { unmount } = layout();
      expect(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Sessions' })).toHaveAttribute(
        'aria-current',
        'page',
      );
      unmount();
    }
  });

  it('has no axe violations', async () => {
    state.path = '/console';
    const { container } = layout();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
