import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ScreenClientError } from '@/lib/screens/client';
import WallReconnectPage, { dynamic, metadata } from './page';

vi.mock('next/navigation', () => ({
  redirect: () => {
    throw new Error('this page never redirects');
  },
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock('@/lib/screens/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/screens/client')>()),
  renewSession: vi.fn(async () => {
    throw Object.assign(new (await import('@/lib/screens/client')).ScreenClientError('not-found'), { disconnected: true });
  }),
  startPairing: vi.fn(() => new Promise(() => {})),
  pollPairing: vi.fn(),
}));

// /screen/reconnect (W9I): where the board sends a display whose wall session the back end no longer
// accepts (a lead disconnected the screen, or its tenant changed). It always shows the pairing screen,
// which asks for a new session from the device cookie and, when that is refused, says "This screen was
// disconnected" and shows a new code. /screen/pair would send a display that still holds a wall session
// back to the board, and the two would loop.

describe('the wall screen reconnect page /screen/reconnect', () => {
  it('is titled for the wall screen, is not for search engines, and is read at every request', () => {
    expect(metadata.title).toBe('DIUCS capacity wall screen');
    expect(metadata.robots).toMatchObject({ index: false });
    expect(dynamic).toBe('force-dynamic');
  });

  it('shows the pairing screen whatever session the display holds, and takes no input', async () => {
    expect(WallReconnectPage.length).toBe(0);
    render(await WallReconnectPage());
    expect(screen.getByRole('heading', { level: 1, name: 'DIUCS capacity wall screen' })).toBeInTheDocument();
    expect(ScreenClientError).toBeDefined();
  });
});
