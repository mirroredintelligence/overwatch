import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { SERVICE_REABLEMENT } from '@/test/fixtures/lead';
import { ChangeNumberForm } from './ChangeNumberForm';

// The change-reporter-number form (W18, pilot): a service's registered number for leave or cover.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('ChangeNumberForm', () => {
  it('posts "this-week" for a cover chosen as This week, then says the new number ends 0456', async () => {
    const user = userEvent.setup();
    render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
    await user.click(await screen.findByRole('button', { name: 'This week' }));
    await user.type(screen.getByLabelText('New mobile number'), '07700 900456');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('New number ending 0456 saved');
    expect(seenLeadPosts).toHaveLength(1);
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/reporters/number',
      csrf: 'test-csrf-token',
      body: { serviceId: SERVICE_REABLEMENT, newNumber: '07700 900456', until: 'this-week' },
    });
    expect(seenLeadPosts[0].idempotencyKey).toBeTruthy();
  });

  it('never shows the full new number after saving, and clears the field', async () => {
    const user = userEvent.setup();
    render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
    const field = await screen.findByLabelText('New mobile number');
    await user.type(field, '07700 900456');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('status');
    expect(document.body.textContent ?? '').not.toMatch(/07700\s?900456/);
    await waitFor(() => expect(field).toHaveValue(''));
  });

  it('says the old number stops working as soon as it is saved', async () => {
    render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
    expect(
      await screen.findByText('The old number stops working as soon as you save. Both numbers are logged.'),
    ).toBeInTheDocument();
  });

  it('offers a test text only after the number is saved', async () => {
    const user = userEvent.setup();
    render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
    expect(await screen.findByRole('button', { name: 'Send a test text' })).toBeDisabled();
    await user.type(await screen.findByLabelText('New mobile number'), '07700 900456');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('status');
    expect(screen.getByRole('button', { name: 'Send a test text' })).toBeEnabled();
  });

  it('refuses a number that is not a UK mobile', async () => {
    const user = userEvent.setup();
    render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
    await user.type(await screen.findByLabelText('New mobile number'), '0123');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a UK mobile number, like 07700 900456');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(<ChangeNumberForm serviceId={SERVICE_REABLEMENT} />);
    await screen.findByRole('button', { name: 'Save' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
