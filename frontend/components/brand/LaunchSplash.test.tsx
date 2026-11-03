import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LaunchSplash } from './LaunchSplash';

const browserTab = (() => ({ matches: false }) as MediaQueryList) as Window['matchMedia'];

describe('LaunchSplash', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function installed(reducedMotion = false) {
    vi.stubGlobal(
      'matchMedia',
      (query: string) => ({ matches: query === '(display-mode: standalone)' || (reducedMotion && query.includes('reduce')) }),
    );
  }

  it('shows nothing in a browser tab', () => {
    vi.stubGlobal('matchMedia', browserTab);
    const { container } = render(<LaunchSplash />);
    act(() => void vi.advanceTimersByTime(100));
    expect(container.querySelector('[data-el="LAUNCH-SPLASH"]')).toBeNull();
  });

  it('shows the splash after the page, lets taps through, hides it from assistive technology, then removes it', () => {
    installed();
    const { container } = render(<LaunchSplash />);
    expect(container.querySelector('[data-el="LAUNCH-SPLASH"]')).toBeNull(); // not before the page has painted
    act(() => void vi.advanceTimersByTime(10));
    const overlay = container.querySelector<HTMLElement>('[data-el="LAUNCH-SPLASH"]');
    expect(overlay).not.toBeNull();
    expect(overlay).toHaveAttribute('aria-hidden', 'true');
    expect(JSON.parse(overlay?.dataset.css ?? '{}')).toEqual({ pointerEvents: 'none' });
    act(() => void vi.advanceTimersByTime(3000));
    expect(container.querySelector('[data-el="LAUNCH-SPLASH"]')).toBeNull();
  });

  it('does not show again on a second mount in the same session', () => {
    installed();
    const first = render(<LaunchSplash />);
    act(() => void vi.advanceTimersByTime(10));
    first.unmount();
    const second = render(<LaunchSplash />);
    act(() => void vi.advanceTimersByTime(10));
    expect(second.container.querySelector('[data-el="LAUNCH-SPLASH"]')).toBeNull();
  });

  it('under reduced motion holds the finished logo only briefly', () => {
    installed(true);
    const { container } = render(<LaunchSplash />);
    act(() => void vi.advanceTimersByTime(10));
    expect(container.querySelector('[data-el="LAUNCH-SPLASH"]')).not.toBeNull();
    act(() => void vi.advanceTimersByTime(600));
    expect(container.querySelector('[data-el="LAUNCH-SPLASH"]')).toBeNull();
  });
});
