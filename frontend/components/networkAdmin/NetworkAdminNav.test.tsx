import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

let pathname = '/network-admin';
vi.mock('next/navigation', () => ({ usePathname: () => pathname }));

import { NetworkAdminNav } from './NetworkAdminNav';

describe('the network administration’s navigation (TEN-080)', () => {
  it('names the four pages and marks the current one with aria-current', () => {
    pathname = '/network-admin/grants';
    render(<NetworkAdminNav />);
    const nav = screen.getByRole('navigation', { name: 'Network administration' });
    expect([...nav.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href'), a.getAttribute('aria-current')])).toEqual([
      ['Members', '/network-admin', null],
      ['Grants', '/network-admin/grants', 'page'],
      ['Listings', '/network-admin/listings', null],
      ['History', '/network-admin/history', null],
    ]);
  });

  it('marks Members only on its own page, not on every page under it', () => {
    pathname = '/network-admin';
    render(<NetworkAdminNav />);
    expect(screen.getByRole('link', { name: 'Members' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Grants' })).not.toHaveAttribute('aria-current');
  });

  it('has no accessibility violation', async () => {
    pathname = '/network-admin/listings';
    render(<NetworkAdminNav />);
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
