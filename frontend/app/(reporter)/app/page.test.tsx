import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '@/lib/auth/session';

const { redirect, getSession } = vi.hoisted(() => ({
  redirect: vi.fn((to: string) => {
    throw new Error(`redirect:${to}`);
  }),
  getSession: vi.fn<() => Promise<Session | null>>(),
}));
vi.mock('next/navigation', () => ({ redirect }));
vi.mock('@/lib/auth/session', () => ({ getSession }));

import AppHome from './page';

// The app's front door (W35, W8E): where a signed-in reporter lands, by the services they signed in with.
const session = (role: Session['role'], services: string[]) => ({ role, services }) as Session;
const goes = async () => AppHome().then(() => 'no redirect', (error: Error) => error.message);

beforeEach(() => {
  redirect.mockClear();
  getSession.mockReset();
});

describe('/app', () => {
  it('goes to the PIN screen with no session, or one that is not a reporter’s', async () => {
    getSession.mockResolvedValue(null);
    expect(await goes()).toBe('redirect:/app/pin');
    getSession.mockResolvedValue(session('lead', ['s1']));
    expect(await goes()).toBe('redirect:/app/pin');
  });

  it('goes to the one service’s update, to the grouped update for several, and to the list for none', async () => {
    getSession.mockResolvedValue(session('reporter', ['s1']));
    expect(await goes()).toBe('redirect:/app/respond/s1');
    getSession.mockResolvedValue(session('reporter', ['s1', 's2']));
    expect(await goes()).toBe('redirect:/app/update');
    // A reporter with no live post has nothing to answer: the list says so, not the PIN screen again.
    getSession.mockResolvedValue(session('reporter', []));
    expect(await goes()).toBe('redirect:/app/services');
  });
});
