import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { AddServiceForm } from './AddServiceForm';

// The shift lead's add-a-service form (W18, pilot). The form posts JSON to the BFF, which sends the
// FHIR Parameters to the back end's $setup. Validation is shown in a summary and inline.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

async function fillValid(user = userEvent.setup()) {
  await user.type(screen.getByLabelText('Service name'), 'Reablement');
  await user.click(screen.getByRole('button', { name: 'Reablement' }));
  await user.type(screen.getByLabelText('Unit label'), 'referrals in the next 2 hrs');
  await user.click(screen.getByRole('button', { name: 'Referrals in the next 2 hrs' }));
  await user.type(screen.getByLabelText('Established capacity'), '4');
  await user.type(screen.getByLabelText('Lowest usual number'), '0');
  await user.type(screen.getByLabelText('Highest usual number'), '8');
  await user.click(screen.getByRole('button', { name: 'Every 2 hrs' }));
  await user.type(screen.getByLabelText('Mobile number for text'), '07700 900456');
  await user.type(screen.getByLabelText('Who holds this phone'), 'Duty manager');
  await user.type(screen.getByLabelText('From'), '08:00');
  await user.type(screen.getByLabelText('To'), '20:00');
  await user.click(screen.getByRole('button', { name: 'Frailty' }));
  await user.type(screen.getByLabelText('Youngest age'), '18');
  await user.type(screen.getByLabelText('Postcode districts'), 'DT4');
  await user.type(screen.getByLabelText('Review criteria by'), '2031-01-31');
  return user;
}

describe('AddServiceForm', () => {
  it('shows an error summary with a link to each problem, and moves focus to it', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await user.click(screen.getByRole('button', { name: 'Save' }));
    const summary = await screen.findByRole('alert');
    expect(summary).toHaveTextContent(/There are \d+ problems/);
    expect(summary).toHaveFocus();
    const link = within(summary).getByRole('link', { name: 'Enter the service name' });
    await user.click(link);
    expect(screen.getByLabelText('Service name')).toHaveFocus();
  });

  it('accepts 07700 900456 and refuses 0123 with the mobile message', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await user.type(screen.getByLabelText('Mobile number for text'), '0123');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findAllByText('Enter a UK mobile number, like 07700 900456')).not.toHaveLength(0);
    await user.clear(screen.getByLabelText('Mobile number for text'));
    await user.type(screen.getByLabelText('Mobile number for text'), '07700 900456');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(screen.queryAllByText('Enter a UK mobile number, like 07700 900456')).toHaveLength(0),
    );
  });

  it('refuses a highest usual number below the lowest', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await user.type(screen.getByLabelText('Lowest usual number'), '5');
    await user.type(screen.getByLabelText('Highest usual number'), '4');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(
      (await screen.findAllByText('Highest usual number must be at least the lowest')).length,
    ).toBeGreaterThan(0);
  });

  it('posts the form as JSON with the CSRF token and an idempotency key, then says Saved and enables the test prompt', async () => {
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await fillValid(user);
    expect(screen.getByRole('button', { name: 'Send a test prompt' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved');
    expect(seenLeadPosts).toHaveLength(1);
    const [post] = seenLeadPosts;
    expect(post.csrf).toBe('test-csrf-token');
    expect(post.idempotencyKey).toBeTruthy();
    expect(post.body).toMatchObject({
      name: 'Reablement',
      category: 'reablement',
      measure: 'referrals-acceptable',
      cadence: 'every-2-hrs',
      channel: 'text',
      mobile: '07700 900456',
      ageMin: 18,
      districts: ['DT4'],
      accepts: ['frailty'],
    });
    expect(screen.getByRole('button', { name: 'Send a test prompt' })).toBeEnabled();
  });

  it('has no axe violations with the errors shown', async () => {
    const user = userEvent.setup();
    const { container } = render(<AddServiceForm />);
    await user.type(screen.getByLabelText('Mobile number for text'), '0123');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('alert');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says the pilot is for text or email only', () => {
    render(<AddServiceForm />);
    expect(screen.getByText('Services with neither text nor email are outside the MVP.')).toBeInTheDocument();
  });

  it('keeps the same idempotency key when a failed save is sent again', async () => {
    server.use(
      http.post('/api/bff/lead/services', ({ request }) => {
        seenLeadPosts.push({
          path: '/api/bff/lead/services',
          csrf: request.headers.get('x-csrf-token'),
          idempotencyKey: request.headers.get('idempotency-key'),
          body: undefined,
        });
        return HttpResponse.json({ code: 'exception', message: 'x' }, { status: 503 });
      }),
    );
    const user = userEvent.setup();
    render(<AddServiceForm />);
    await fillValid(user);
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not be saved.');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(seenLeadPosts).toHaveLength(2));
    expect(seenLeadPosts[1].idempotencyKey).toBe(seenLeadPosts[0].idempotencyKey);
  });
});
