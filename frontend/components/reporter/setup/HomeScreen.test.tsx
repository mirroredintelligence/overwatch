import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { HomeScreen } from './HomeScreen';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15';
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120';

function setAgent(agent: string) {
  Object.defineProperty(navigator, 'userAgent', { configurable: true, value: agent });
}

beforeEach(() => push.mockClear());
afterEach(() => setAgent(navigator.userAgent));

describe('HomeScreen', () => {
  it('shows the iPhone guide for an iPhone, with the iOS version it needs, and passes axe', async () => {
    setAgent(IPHONE);
    const { container } = render(<HomeScreen />);
    expect(screen.getByRole('heading', { name: 'Add DIUCS to your home screen' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'iPhone', selected: true })).toBeInTheDocument();
    expect(screen.getByText('iPhone needs iOS 16.4 or later.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the Android guide for an Android phone', () => {
    setAgent(ANDROID);
    render(<HomeScreen />);
    expect(screen.getByRole('tab', { name: 'Android', selected: true })).toBeInTheDocument();
  });

  it('says to open from the home screen when pressed in a browser tab, and carries on from the home screen', async () => {
    setAgent(IPHONE);
    render(<HomeScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'I have added it' }));
    expect(
      screen.getByText('Open DIUCS from your home screen to carry on. Notifications only work from there.'),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('ends set-up by text when the reporter cannot add it', async () => {
    setAgent(IPHONE);
    render(<HomeScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'I cannot do this. Use text instead' }));
    expect(push).toHaveBeenCalledWith('/setup/done?channel=text');
  });
});
