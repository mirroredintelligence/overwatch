import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CallBar } from './CallBar';

const OPENED = '2026-10-30T10:00:00.000Z';

afterEach(() => {
  vi.useRealTimers();
});

describe('CallBar (W10)', () => {
  it('shows the call, the timer from openedAt and the referrer', () => {
    vi.useFakeTimers({ now: new Date(OPENED) });
    render(<CallBar openedAt={OPENED} referrer="Ambulance crew" />);

    expect(screen.getByText('Call in progress · 00:00 · Ambulance crew')).toBeInTheDocument();
  });

  it('shows 02:14 after 134 seconds, updating each second', () => {
    vi.useFakeTimers({ now: new Date(OPENED) });
    render(<CallBar openedAt={OPENED} referrer="Ambulance crew" />);

    act(() => {
      vi.advanceTimersByTime(134_000);
    });

    expect(screen.getByText('Call in progress · 02:14 · Ambulance crew')).toBeInTheDocument();
  });

  it('is not a live region, so the timer is not read out every second', () => {
    render(<CallBar openedAt={OPENED} referrer="Ambulance crew" />);

    expect(document.querySelector('[role="status"],[role="alert"],[aria-live]')).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(<CallBar openedAt={OPENED} referrer="Ambulance crew" />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
