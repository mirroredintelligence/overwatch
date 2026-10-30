import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_ALERT_PREFERENCES } from '@/lib/exec/alertPrefs';
import { server } from '@/test/msw/server';
import { SetupFlow } from './SetupFlow';

// Where the executive's set-up ends (W39, W9H DEC-1040): an executive goes on to switch on alerts on their
// phone, a lead (who has no phone app) to the home screen. The page chooses; the flow goes where it is told.

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const initial = { ...DEFAULT_ALERT_PREFERENCES, deputy: 'lead-1' };

async function throughToSave() {
  await userEvent.click(screen.getByRole('button', { name: 'Choose my alerts' }));
  await userEvent.click(screen.getByRole('button', { name: 'Save my alerts' }));
  await userEvent.click(screen.getByRole('button', { name: 'Save' }));
}

beforeEach(() => {
  push.mockClear();
  server.use(
    http.put('/api/bff/exec/alert-preferences', () => HttpResponse.json({ ...initial })),
  );
});

describe('SetupFlow', () => {
  it('goes on to the phone alerts when the page says so', async () => {
    render(<SetupFlow initial={initial} leaders={[{ id: 'lead-1', name: 'Sample Lead' }]} next="/planning/phone" />);
    await throughToSave();
    await waitFor(() => expect(push).toHaveBeenCalledWith('/planning/phone'));
  });

  it('goes to the home screen when the page names no other place', async () => {
    render(<SetupFlow initial={initial} leaders={[{ id: 'lead-1', name: 'Sample Lead' }]} />);
    await throughToSave();
    await waitFor(() => expect(push).toHaveBeenCalledWith('/planning'));
  });

  it('does not go on when the save fails', async () => {
    server.use(http.put('/api/bff/exec/alert-preferences', () => HttpResponse.json({ code: 'exception' }, { status: 500 })));
    render(<SetupFlow initial={initial} leaders={[{ id: 'lead-1', name: 'Sample Lead' }]} next="/planning/phone" />);
    await throughToSave();
    expect(await screen.findByText('Could not save your choices. Try again.')).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
