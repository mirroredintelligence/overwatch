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
vi.mock('@/components/exec/PhoneAlerts', () => ({ PhoneAlerts: () => null }));

import PhonePage from './page';

// Alerts on the phone are the executive's (W9H, DEC-1040): the notification routes admit an executive
// and a reporter, so a lead on this address goes to the home screen rather than to a button that fails.
const session = (role: Session['role']) => ({ role }) as Session;
const goes = async () => PhonePage().then(() => 'renders', (error: Error) => error.message);

beforeEach(() => {
  redirect.mockClear();
  getSession.mockReset();
});

describe('/planning/phone', () => {
  it('renders for an executive', async () => {
    getSession.mockResolvedValue(session('exec'));
    expect(await goes()).toBe('renders');
  });

  it('goes to sign-in with no session, and to the home screen for a lead', async () => {
    getSession.mockResolvedValue(null);
    expect(await goes()).toBe('redirect:/sign-in');
    getSession.mockResolvedValue(session('lead'));
    expect(await goes()).toBe('redirect:/planning');
  });

  it.each(['reporter', 'advisor', 'clinical', 'owner', 'wall', 'support'] as const)('goes to sign-in for a %s session', async (role) => {
    getSession.mockResolvedValue(session(role));
    expect(await goes()).toBe('redirect:/sign-in');
  });
});
