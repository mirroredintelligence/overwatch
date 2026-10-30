import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { NotificationsOff } from './NotificationsOff';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
});

describe('NotificationsOff', () => {
  it('explains the three steps and passes axe', async () => {
    const { container } = render(<NotificationsOff />);
    expect(screen.getByRole('heading', { name: 'Notifications are off' })).toBeInTheDocument();
    expect(screen.getByText('We cannot alert you. Turn them on in your phone settings, or switch to text.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says they are still off when permission is still denied, and goes back to settings when granted', async () => {
    vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'denied' }));
    render(<NotificationsOff />);
    await userEvent.click(screen.getByRole('button', { name: 'I have turned them on' }));
    expect(await screen.findByText('Notifications are still off.')).toBeInTheDocument();
    vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'granted' }));
    await userEvent.click(screen.getByRole('button', { name: 'I have turned them on' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/settings'));
    vi.unstubAllGlobals();
  });
});
