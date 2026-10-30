import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { CSRF_TOKEN } from '@/test/msw/handlers/advisor';
import { server } from '@/test/msw/server';
import { PhonedDialog } from './PhonedDialog';

type Sent = { body: unknown; csrf: string | null; key: string | null; url: string };
const sent: Sent[] = [];

beforeEach(() => {
  resetCsrfCache();
  sent.length = 0;
  server.use(
    http.post('/api/bff/services/:id/phoned', async ({ request }) => {
      sent.push({
        body: await request.json(),
        csrf: request.headers.get('x-csrf-token'),
        key: request.headers.get('idempotency-key'),
        url: request.url,
      });
      return HttpResponse.json({ recorded: true }, { status: 201 });
    }),
  );
});

function renderDialog(onSaved = vi.fn(), onClose = vi.fn()) {
  render(
    <PhonedDialog caseRef="4821" serviceId="svc-ucr-west" serviceName="UCR West" onSaved={onSaved} onClose={onClose} />,
  );
  return { onSaved, onClose };
}

describe('PhonedDialog (W14)', () => {
  it('Limited with 1 posts the position with CSRF and an Idempotency-Key, then closes and refreshes', async () => {
    const user = userEvent.setup();
    const { onSaved, onClose } = renderDialog();

    await user.click(screen.getByRole('button', { name: 'Limited' }));
    await user.type(screen.getByLabelText('How many can they take?'), '1');
    await user.click(byEl('ADV-PHONED-SAVE-BTN'));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalled();
    expect(sent).toHaveLength(1);
    expect(sent[0].body).toEqual({ said: 'limited', value: 1, caseRef: '4821' });
    expect(sent[0].csrf).toBe(CSRF_TOKEN);
    expect(sent[0].key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(sent[0].url).not.toMatch(/4821|svc-ucr-west/);
  });

  it('Not accepting hides the number and sends 0', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole('button', { name: 'Not accepting' }));
    expect(screen.queryByLabelText('How many can they take?')).toBeNull();
    await user.click(byEl('ADV-PHONED-SAVE-BTN'));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].body).toEqual({ said: 'not-accepting', value: 0, caseRef: '4821' });
  });

  it('Accepting with an empty number shows the error and posts nothing', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderDialog();

    await user.click(screen.getByRole('button', { name: 'Accepting' }));
    await user.click(byEl('ADV-PHONED-SAVE-BTN'));

    expect(screen.getByText('Enter how many they can take, as a whole number')).toBeInTheDocument();
    expect(screen.getByLabelText('How many can they take?')).toHaveAttribute('aria-invalid', 'true');
    expect(sent).toHaveLength(0);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('a number that is not whole is refused the same way', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('button', { name: 'Limited' }));
    await user.type(screen.getByLabelText('How many can they take?'), '1.5');
    await user.click(byEl('ADV-PHONED-SAVE-BTN'));

    expect(screen.getByText('Enter how many they can take, as a whole number')).toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it('Save is disabled until the answer is chosen, and the note says it updates the board', () => {
    renderDialog();

    expect(byEl('ADV-PHONED-SAVE-BTN')).toBeDisabled();
    expect(screen.getByText('Updates the board for everyone. Recorded as “advisor phoned”.')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'I phoned' })).toBeInTheDocument();
    expect(screen.getByText('UCR West')).toBeInTheDocument();
  });

  it('Cancel closes without posting', async () => {
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onClose).toHaveBeenCalled();
    expect(sent).toHaveLength(0);
  });

  it('has no axe violations when open', async () => {
    renderDialog();
    expect((await runAxe(document.body)).violations).toEqual([]);
  });
});
