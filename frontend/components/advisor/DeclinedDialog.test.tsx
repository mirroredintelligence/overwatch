import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { server } from '@/test/msw/server';
import { DeclinedDialog } from './DeclinedDialog';

const sent: unknown[] = [];

beforeEach(() => {
  resetCsrfCache();
  sent.length = 0;
  server.use(
    http.post('/api/bff/services/:id/declined', async ({ request }) => {
      sent.push(await request.json());
      return HttpResponse.json({ recorded: true }, { status: 201 });
    }),
  );
});

function renderDialog(onSaved = vi.fn(), onClose = vi.fn()) {
  render(
    <DeclinedDialog caseRef="4821" serviceId="svc-ucr-west" serviceName="UCR West" onSaved={onSaved} onClose={onClose} />,
  );
  return { onSaved, onClose };
}

describe('DeclinedDialog (W14)', () => {
  it('shows the question, the four reasons and the note that it is not used to assess advisors', () => {
    renderDialog();

    expect(screen.getByRole('dialog', { name: 'They declined' })).toBeInTheDocument();
    expect(screen.getByText('The board showed capacity')).toBeInTheDocument();
    expect(screen.getByText('Why did UCR West decline?')).toBeInTheDocument();
    for (const reason of ['Full, not yet reported', 'Outside their criteria', 'Staffing or transport', 'Other']) {
      expect(screen.getByRole('button', { name: reason })).toBeInTheDocument();
    }
    expect(screen.getByText('For a conversation with the service. Not used to assess advisors.')).toBeInTheDocument();
  });

  it('Save is disabled until a reason is chosen', async () => {
    const user = userEvent.setup();
    renderDialog();
    expect(byEl('ADV-DECLINED-SAVE-BTN')).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Outside their criteria' }));
    expect(byEl('ADV-DECLINED-SAVE-BTN')).toBeEnabled();
  });

  it('"Outside their criteria" posts outside-criteria with the case, then closes and refreshes', async () => {
    const user = userEvent.setup();
    const { onSaved, onClose } = renderDialog();

    await user.click(screen.getByRole('button', { name: 'Outside their criteria' }));
    await user.click(byEl('ADV-DECLINED-SAVE-BTN'));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalled();
    expect(sent).toEqual([{ reason: 'outside-criteria', caseRef: '4821' }]);
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
