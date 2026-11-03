import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { HomeScreen } from './HomeScreen';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15';
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120';

function setAgent(agent: string) {
  Object.defineProperty(navigator, 'userAgent', { configurable: true, value: agent });
}

beforeEach(() => {
  push.mockClear();
  resetReporterRequests();
});
afterEach(() => setAgent(navigator.userAgent));

describe('HomeScreen', () => {
  it('shows the iPhone guide for an iPhone, with the iOS version it needs, and passes axe', async () => {
    setAgent(IPHONE);
    const { container } = render(<HomeScreen />);
    expect(screen.getByRole('heading', { name: 'Add Overwatch to your home screen' })).toBeInTheDocument();
    expect(screen.getByRole('tablist', { name: 'Your phone' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'iPhone', selected: true })).toBeInTheDocument();
    expect(screen.getByText('iPhone needs iOS 16.4 or later.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the step caption and a five-segment progress bar at step 3 of 5, inside the provider shell', () => {
    setAgent(IPHONE);
    render(<HomeScreen />);
    expect(screen.getByText('Step 3 of 5')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Step 3 of 5' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toContainElement(screen.getByRole('heading', { name: 'Add Overwatch to your home screen' }));
  });

  it('gives each iPhone step the line the artboard puts under it (R5, Add to home screen)', () => {
    setAgent(IPHONE);
    render(<HomeScreen />);
    const items = within(screen.getByRole('list', { name: 'Add to home screen on iPhone' })).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent('Tap ShareThe square with an arrow, at the bottom of the screen');
    expect(items[1]).toHaveTextContent('Scroll down the list if you cannot see it');
    expect(items[2]).toHaveTextContent('The Overwatch icon appears on your home screen');
    expect(items[3]).toHaveTextContent('Open it from the home screen');
    expect(items[3]).toHaveTextContent('Carry on there. Notifications only work from the home screen.');
  });

  it('gives each step an icon tile that screen readers skip', () => {
    setAgent(IPHONE);
    render(<HomeScreen />);
    const items = within(screen.getByRole('list', { name: 'Add to home screen on iPhone' })).getAllByRole('listitem');
    for (const item of items) {
      expect(item.querySelector('[data-step-icon]')).toHaveAttribute('aria-hidden', 'true');
    }
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
      screen.getByText('Open Overwatch from your home screen to carry on. Notifications only work from there.'),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('ends set-up by text when the reporter cannot add it', async () => {
    setAgent(IPHONE);
    render(<HomeScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'I cannot do this. Use text instead' }));
    expect(push).toHaveBeenCalledWith('/setup/done?channel=text');
    // Before sign-in: recorded for the phone's device, not behind a session (W8E).
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/channel')?.body).toEqual({ channel: 'text' });
    expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/channel')).toBe(false);
  });

  it('stays on the guide and says so when the channel could not be saved', async () => {
    setAgent(IPHONE);
    server.use(http.post('/api/bff/identity/channel', () => HttpResponse.json({ code: 'needs-code' }, { status: 403 })));
    render(<HomeScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'I cannot do this. Use text instead' }));
    expect(await screen.findByText('We could not save that. Check your number again, then try once more.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it('carries a reporter already in the installed app straight on to notifications', async () => {
    setAgent(IPHONE);
    Object.defineProperty(navigator, 'standalone', { configurable: true, value: true });
    try {
      render(<HomeScreen />);
      expect(screen.getByRole('heading', { name: 'Welcome. Your set-up continues here.' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
      expect(push).toHaveBeenCalledWith('/setup/notifications');
    } finally {
      Object.defineProperty(navigator, 'standalone', { configurable: true, value: undefined });
    }
  });
});
