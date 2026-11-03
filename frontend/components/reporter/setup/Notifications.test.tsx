import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { Notifications } from './Notifications';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const requestPermission = vi.fn<() => Promise<NotificationPermission>>();

beforeEach(() => {
  push.mockClear();
  resetReporterRequests();
  requestPermission.mockReset();
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'default', requestPermission }));
});

afterEach(() => vi.unstubAllGlobals());

describe('Notifications', () => {
  it('says what is sent and never asks for permission on render, and passes axe', async () => {
    const { container } = render(<Notifications service="UCR West" />);
    expect(screen.getByRole('heading', { name: 'Turn on notifications' })).toBeInTheDocument();
    expect(screen.getByText('What we send')).toBeInTheDocument();
    expect(screen.getByText('Capacity requests and booking requests for UCR West.')).toBeInTheDocument();
    expect(screen.getByText('What we never send')).toBeInTheDocument();
    expect(screen.getByText('Patient names or details.')).toBeInTheDocument();
    expect(screen.getByText('You choose')).toBeInTheDocument();
    expect(screen.getByText('Turn them off any time in Settings.')).toBeInTheDocument();
    expect(screen.getByText('When you allow, we record the date and this phone.')).toBeInTheDocument();
    expect(requestPermission).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows step 4 of 5 as the caption and in the progress bar', () => {
    render(<Notifications service="UCR West" />);
    expect(screen.getByText('Step 4 of 5')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Step 4 of 5' })).toBeInTheDocument();
  });

  it('disables Allow and marks it busy while the browser is asking, so a second press does nothing', async () => {
    let answer!: (permission: NotificationPermission) => void;
    requestPermission.mockReturnValue(new Promise<NotificationPermission>((resolve) => (answer = resolve)));
    render(<Notifications service="UCR West" />);
    await userEvent.click(screen.getByRole('button', { name: 'Allow notifications' }));
    const allow = screen.getByRole('button', { name: 'Allow notifications' });
    expect(allow).toBeDisabled();
    expect(allow).toHaveAttribute('aria-busy', 'true');
    await act(async () => answer('granted'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/pin'));
    expect(requestPermission).toHaveBeenCalledTimes(1);
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

  it('records text for the phone’s device before sign-in when the reporter would rather have text', async () => {
    render(<Notifications service="UCR West" />);
    await userEvent.click(screen.getByRole('button', { name: 'Not now. Use text instead' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/setup/done?channel=text'));
    expect(seenBffRequests.find((r) => r.path === '/api/bff/identity/channel')?.body).toEqual({ channel: 'text' });
    expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/channel')).toBe(false);
  });
});
