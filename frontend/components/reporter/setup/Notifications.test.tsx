import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Notifications } from './Notifications';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const requestPermission = vi.fn<() => Promise<NotificationPermission>>();

beforeEach(() => {
  push.mockClear();
  requestPermission.mockReset();
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'default', requestPermission }));
});

afterEach(() => vi.unstubAllGlobals());

describe('Notifications', () => {
  it('says what is sent and never asks for permission on render', async () => {
    const { container } = render(<Notifications service="UCR West" />);
    expect(screen.getByText('What we send: Capacity requests and booking requests for UCR West.')).toBeInTheDocument();
    expect(screen.getByText('What we never send: Patient names or details.')).toBeInTheDocument();
    expect(requestPermission).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for permission only after Allow, and moves on when it is granted', async () => {
    requestPermission.mockResolvedValue('granted');
    render(<Notifications service="UCR West" />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow notifications' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/pin'));
    expect(requestPermission).toHaveBeenCalledTimes(1);
  });

  it('links to the notifications-off guidance when permission is denied', async () => {
    requestPermission.mockResolvedValue('denied');
    render(<Notifications service="UCR West" />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow notifications' }));
    expect(await screen.findByRole('link', { name: /notifications are off/i })).toHaveAttribute('href', '/app/notifications-off');
  });
});
