import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ScreenClientError } from '@/lib/screens/client';
import type { PairingApi } from '@/lib/screens/usePairing';
import { runAxe } from '@/test/a11y';
import { PairingScreen } from './PairingScreen';

// The ScreenPairing artboard, step 1: what the wall display shows while it waits to be connected.

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));

function api(over: Partial<PairingApi> = {}): PairingApi {
  return {
    renew: vi.fn(async () => {
      throw new ScreenClientError('not-found');
    }),
    start: vi.fn(async () => ({ pairingId: 'pairing-1', code: '482913', expiresAt: '2026-10-30T09:10:00Z' })),
    poll: vi.fn(async () => 'waiting' as const),
    ...over,
  };
}

async function show(calls: PairingApi) {
  const view = render(<PairingScreen api={calls} />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  return view;
}

beforeEach(() => {
  vi.useFakeTimers();
  replace.mockClear();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('PairingScreen', () => {
  it('shows the artboard’s words and the code as two groups of three', async () => {
    await show(api());
    expect(screen.getByRole('heading', { level: 1, name: 'DIUCS capacity wall screen' })).toBeInTheDocument();
    expect(screen.getByText('482 913')).toBeInTheDocument();
    expect(screen.getByText('Enter this code in the admin page to connect this screen.')).toBeInTheDocument();
    expect(screen.getByText('Waiting to be connected · code works for 10 minutes')).toBeInTheDocument();
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
  });

  it('has the element id for the code, and the code is the only thing in it', async () => {
    const { container } = await show(api());
    expect(container.querySelector('[data-el="WALL-PAIR-CODE"]')?.textContent).toBe('482 913');
  });

  it('shows the code in very large digits (at least the wall board’s big number size)', async () => {
    const { readFileSync } = await import('node:fs');
    const css = readFileSync(new URL('./PairingScreen.module.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    const rule = /\.code\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
    const size = /font-size:\s*([\d.]+)rem/.exec(rule);
    expect(size).not.toBeNull();
    expect(Number(size?.[1]) * 16).toBeGreaterThanOrEqual(96);
    expect(rule).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });

  it('says it is connecting, with no code, before it has one', () => {
    render(<PairingScreen api={api({ start: vi.fn(() => new Promise<never>(() => {})) })} />);
    expect(screen.getByText('Connecting this screen…')).toBeInTheDocument();
    expect(screen.queryByText(/\d{3} \d{3}/)).toBeNull();
  });

  it('goes to the board when it is paired', async () => {
    await show(api({ poll: vi.fn(async () => 'paired' as const) }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(replace).toHaveBeenCalledWith('/screen');
  });

  it('goes to the board at once when it already has a session', async () => {
    await show(api({ renew: vi.fn(async () => undefined) }));
    expect(replace).toHaveBeenCalledWith('/screen');
  });

  it('shows the new code when the old one has expired', async () => {
    let n = 0;
    const calls = api({
      start: vi.fn(async () => ({ pairingId: `p${++n}`, code: n === 1 ? '482913' : '271828', expiresAt: '2026-10-30T09:10:00Z' })),
      poll: vi.fn(async () => 'expired' as const),
    });
    await show(calls);
    expect(screen.getByText('482 913')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByText('271 828')).toBeInTheDocument();
    expect(screen.queryByText('482 913')).toBeNull();
  });

  it('says why there is no code when pairing is throttled or unavailable, in the back end’s words, as an alert', async () => {
    const throttled = new ScreenClientError('throttled');
    await show(api({ start: vi.fn(async () => { throw throttled; }) }));
    expect(screen.getByRole('alert')).toHaveTextContent('Too many attempts. Wait a few minutes and try again.');
  });

  it('says pairing is unavailable, as an alert', async () => {
    await show(api({ start: vi.fn(async () => { throw new ScreenClientError('unavailable'); }) }));
    expect(screen.getByRole('alert')).toHaveTextContent('Pairing is not available right now. Try again shortly.');
  });

  it('announces a changed code politely and not the countdown of anything', async () => {
    const { container } = await show(api());
    const live = container.querySelector('[aria-live]');
    expect(live?.getAttribute('aria-live')).toBe('polite');
    expect(live?.textContent).toContain('482 913');
  });

  it('puts no button, link or input on a wall display: nobody types on it', async () => {
    const { container } = await show(api());
    expect(container.querySelectorAll('button, a, input, select, textarea')).toHaveLength(0);
  });

  it('has no axe violations, with the code, while connecting and with a message', async () => {
    const withCode = await show(api());
    expect(await runAxe(withCode.container)).toHaveNoViolations();
    withCode.unmount();
    const connecting = render(<PairingScreen api={api({ start: vi.fn(() => new Promise<never>(() => {})) })} />);
    expect(await runAxe(connecting.container)).toHaveNoViolations();
    connecting.unmount();
    const message = await show(api({ start: vi.fn(async () => { throw new ScreenClientError('unavailable'); }) }));
    expect(await runAxe(message.container)).toHaveNoViolations();
  });

  it('puts the code in no title, no address and no storage', async () => {
    await show(api());
    expect(document.title).not.toContain('482');
    expect(window.location.href).not.toContain('482913');
    expect(JSON.stringify([localStorage, sessionStorage])).not.toContain('482913');
  });
});
