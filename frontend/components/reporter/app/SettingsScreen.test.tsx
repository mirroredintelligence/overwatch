import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { SettingsScreen } from './SettingsScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const SETTINGS = { channel: 'text', maskedPhone: '07xxx xxx456', maskedCover: null, reverifyInDays: 21, otherDevices: 1 };

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
  server.use(
    http.get('/api/bff/reporter/settings', () => HttpResponse.json(SETTINGS)),
    http.delete('/api/bff/session', () => new HttpResponse(null, { status: 204 })),
  );
});

describe('SettingsScreen', () => {
  it('shows masked values only, and never the full cover number after one is saved', async () => {
    const { container } = render(<SettingsScreen />);
    expect(await screen.findByText('07xxx xxx456')).toBeInTheDocument();
    expect(screen.getByText('In 21 days')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add a cover number' }));
    await userEvent.type(screen.getByLabelText('Cover mobile number'), '07700 900123');
    await userEvent.click(screen.getByRole('button', { name: 'Save cover number' }));
    await waitFor(() => expect(seenBffRequests.some((r) => r.path === '/api/bff/reporter/cover')).toBe(true));
    expect(container.textContent).not.toContain('07700 900123');
    expect(container.textContent).not.toContain('900123');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks in the page before signing the phone out, does nothing on Cancel, and signs out on Confirm', async () => {
    render(<SettingsScreen />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out of this phone' }));
    expect(screen.getByText('Sign out of this phone?')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText('Sign out of this phone?')).toBeNull();
    expect(push).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Sign out of this phone' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app/pin'));
  });
});
