import { http, HttpResponse } from 'msw';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { SERVICE_UCR_EAST } from '@/test/fixtures/lead';
import { LeadPhonedDialog } from './LeadPhonedDialog';

// The shift lead's "Enter what they told me by phone" (W8D, DEC-920): with no case, what a service said on the
// phone and how many it can take. It is a real form now: it posts to the BFF's phoned route with CSRF and a key.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

function renderOpen(onClose = vi.fn(), onRecorded = vi.fn()) {
  render(
    <LeadPhonedDialog open serviceId={SERVICE_UCR_EAST} serviceName="UCR East" onClose={onClose} onRecorded={onRecorded} />,
  );
  return { onClose, onRecorded };
}

describe('LeadPhonedDialog', () => {
  it('shows nothing while closed, and names the service and the answers when open', () => {
    const { unmount } = render(
      <LeadPhonedDialog open={false} serviceId={SERVICE_UCR_EAST} serviceName="UCR East" onClose={vi.fn()} />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    unmount();
    renderOpen();
    expect(screen.getByRole('dialog', { name: 'Enter what they told me by phone' })).toBeInTheDocument();
    expect(screen.getByText('UCR East')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accepting' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Limited' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Not accepting' })).toBeInTheDocument();
  });

  it('posts a limited answer with its figure, the CSRF token and a key, then closes and says it was recorded', async () => {
    const user = userEvent.setup();
    const { onClose, onRecorded } = renderOpen();
    await user.click(screen.getByRole('button', { name: 'Limited' }));
    await user.type(screen.getByLabelText('How many can they take?'), '3');
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onRecorded).toHaveBeenCalled();
    expect(seenLeadPosts).toHaveLength(1);
    expect(seenLeadPosts[0]).toMatchObject({
      path: `/api/bff/lead/services/${SERVICE_UCR_EAST}/phoned`,
      csrf: 'test-csrf-token',
      body: { said: 'limited', value: 3 },
    });
    expect(seenLeadPosts[0].idempotencyKey).toBeTruthy();
  });

  it('takes no figure for not accepting, and posts that answer alone', async () => {
    const user = userEvent.setup();
    renderOpen();
    await user.click(screen.getByRole('button', { name: 'Not accepting' }));
    expect(screen.queryByLabelText('How many can they take?')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0].body).toEqual({ said: 'not-accepting' });
  });

  it('asks for a whole number for accepting and posts nothing when it is not one', async () => {
    const user = userEvent.setup();
    renderOpen();
    await user.click(screen.getByRole('button', { name: 'Accepting' }));
    await user.type(screen.getByLabelText('How many can they take?'), 'four');
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    expect(await screen.findByText('Enter how many they can take, as a whole number')).toBeInTheDocument();
    expect(screen.getByLabelText('How many can they take?')).toHaveAttribute('aria-invalid', 'true');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('says the position could not be saved when the back end refuses, and stays open', async () => {
    server.use(
      http.post(`/api/bff/lead/services/${SERVICE_UCR_EAST}/phoned`, () =>
        HttpResponse.json({ code: 'exception', message: 'x' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    const { onClose } = renderOpen();
    await user.click(screen.getByRole('button', { name: 'Not accepting' }));
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The position could not be saved. Try again.');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('is accessible with an answer chosen and an error shown', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <LeadPhonedDialog open serviceId={SERVICE_UCR_EAST} serviceName="UCR East" onClose={vi.fn()} />,
    );
    await user.click(screen.getByRole('button', { name: 'Accepting' }));
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
