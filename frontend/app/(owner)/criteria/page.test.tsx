import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { Session } from '@/lib/auth/session';
import CriteriaLandingPage from './page';

// DEC-1306: the criteria owner's landing at /criteria. The services are the session's own list.

const getSession = vi.fn<() => Promise<Session | null>>();
const redirect = vi.fn((to: string): never => {
  throw new Error(`REDIRECT:${to}`);
});
vi.mock('@/lib/auth/session', () => ({ getSession: () => getSession() }));
vi.mock('next/navigation', () => ({ redirect: (to: string) => redirect(to) }));

function session(role: Session['role'], services: string[]): Session {
  return { role, services, tenantId: 't', host: 'h', sub: 's', backendToken: 'x', expiresAt: '2999-01-01T00:00:00Z' };
}

beforeEach(() => {
  getSession.mockReset();
  redirect.mockClear();
});

describe('the criteria landing page', () => {
  it('lists each service the owner can review, each linking to its overview, under one h1', async () => {
    getSession.mockResolvedValue(session('owner', ['s1', 'urgent care/2']));
    const { container } = render(await CriteriaLandingPage());
    expect(screen.getByRole('heading', { level: 1, name: 'Your services' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    const links = within(screen.getByRole('list')).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/criteria/s1', '/criteria/urgent%20care%2F2']);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('goes straight to the overview when there is one service', async () => {
    getSession.mockResolvedValue(session('owner', ['s1']));
    await expect(CriteriaLandingPage()).rejects.toThrow('REDIRECT:/criteria/s1');
  });

  it('says there is nothing to review, with the Help link, when the list is empty', async () => {
    getSession.mockResolvedValue(session('owner', []));
    const { container } = render(await CriteriaLandingPage());
    expect(screen.getByRole('heading', { level: 1, name: 'Your services' })).toBeInTheDocument();
    expect(screen.getByText('No services to review')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
    expect(screen.queryByRole('list')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('sends a visitor with no session to sign in, and a role that is not a reviewer away', async () => {
    getSession.mockResolvedValue(null);
    await expect(CriteriaLandingPage()).rejects.toThrow('REDIRECT:/sign-in');
    getSession.mockResolvedValue(session('advisor', ['s1']));
    await expect(CriteriaLandingPage()).rejects.toThrow('REDIRECT:/sign-in');
  });
});
