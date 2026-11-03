import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { TabBar } from './TabBar';

// The installed app's bottom bar (artboards B6 and B9): Update, Services, Settings, Help.

describe('TabBar', () => {
  it('is a navigation with the four tabs, each a link', async () => {
    const { container } = render(<TabBar pathname="/app/services" />);
    const nav = screen.getByRole('navigation', { name: 'App' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((l) => l.textContent)).toEqual(['Update', 'Services', 'Settings', 'Help']);
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/app', '/app/services', '/app/settings', '/help']);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('marks the tab of the current page, and only that one', () => {
    render(<TabBar pathname="/app/settings" />);
    const current = screen.getAllByRole('link').filter((l) => l.getAttribute('aria-current') === 'page');
    expect(current.map((l) => l.textContent)).toEqual(['Settings']);
  });

  it.each(['/app', '/app/update', '/app/respond/svc-1', '/app/respond/svc-1/thanks', '/app/booking/4821'])('treats %s as the Update tab', (path) => {
    render(<TabBar pathname={path} />);
    expect(screen.getByRole('link', { name: 'Update' })).toHaveAttribute('aria-current', 'page');
  });

  it('keeps Services current on a page below it', () => {
    render(<TabBar pathname="/app/services/abc/cover" />);
    expect(screen.getByRole('link', { name: 'Services' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Update' })).not.toHaveAttribute('aria-current');
  });

  it('draws a picture over each word, hidden from a screen reader', () => {
    const { container } = render(<TabBar pathname="/app" />);
    const svgs = container.querySelectorAll('a svg');
    expect(svgs).toHaveLength(4);
    svgs.forEach((svg) => expect(svg).toHaveAttribute('aria-hidden', 'true'));
  });
});
