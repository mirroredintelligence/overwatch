import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { CreateTenantForm } from './CreateTenantForm';

// Creating a tenant (TEN-083): the operator names it and gives its id. The id is a path of the call, never a
// field of its body. A creation that stopped is finished by sending the same again.

beforeEach(() => resetOperatorWrites());

async function fill(user: ReturnType<typeof userEvent.setup>, over: Partial<Record<string, string>> = {}) {
  const values: Record<string, string> = { 'Tenant id': 'trust-d', 'Display name': 'Sample Area D', 'Legal name': 'Sample Area D Organisation', ...over };
  for (const [label, value] of Object.entries(values)) {
    const field = screen.getByLabelText(label);
    await user.clear(field);
    if (value !== '') await user.type(field, value);
  }
}

describe('CreateTenantForm', () => {
  it('has the fields of a tenant, with the country and the time zone filled in', () => {
    render(<CreateTenantForm />);
    expect(screen.getByRole('heading', { level: 1, name: 'Create a tenant' })).toBeInTheDocument();
    expect(screen.getByLabelText('Country code')).toHaveValue('GB');
    expect(screen.getByLabelText('Time zone')).toHaveValue('Europe/London');
    const types = within(screen.getByRole('combobox', { name: 'Organisation type' })).getAllByRole('option').map((o) => o.textContent);
    expect(types).toEqual(['NHS trust', 'Integrated care board', 'GP practice', 'Local authority', 'Voluntary or independent', 'Other']);
  });

  it('creates the tenant at the path of its id, with no id in the body, and says what comes next', async () => {
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user, { 'ODS code': 'RZZ03' });
    await user.selectOptions(screen.getByRole('combobox', { name: 'Organisation type' }), 'gp-practice');
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    const write = seenOperatorWrites[0]!;
    expect(write).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-d', csrf: OPERATOR_SAMPLE_CSRF });
    expect(write.key).toBeTruthy();
    expect(write.body).toEqual({ displayName: 'Sample Area D', legalName: 'Sample Area D Organisation', organisationType: 'gp-practice', odsCode: 'RZZ03', countryCode: 'GB', timeZone: 'Europe/London' });
    const done = await screen.findByRole('status');
    expect(done).toHaveTextContent('Tenant created. It is being set up.');
    expect(within(done).getByRole('link', { name: 'Open the tenant' })).toHaveAttribute('href', '/operator/tenants/trust-d');
  });

  it('says a creation that had stopped is finished, on a 200', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id', () => HttpResponse.json({ created: false, recorded: true })));
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The creation had stopped before. It is finished now.');
  });

  it('says the step was done and not recorded, and does not offer to do it again, when recorded is false', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id', () => HttpResponse.json({ created: true, recorded: false }, { status: 201 })));
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The tenant was created, but the platform record could not be written. Do not create it again.');
    expect(screen.queryByRole('button', { name: 'Create tenant' })).not.toBeInTheDocument();
  });

  it('refuses an id that is not the shape of one, and a missing name, in words, and sends nothing', async () => {
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user, { 'Tenant id': 'Bad Id!', 'Display name': '' });
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect(await screen.findByText('Use 2 to 31 lower-case letters, digits or hyphens, starting with a letter or a digit.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Enter the name people know the organisation by.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('There are 2 problems');
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says the id is taken on a 409, and could not be created on another failure', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That id cannot be used. It may be taken, or the tenant is past the point where it can be created again.');
    server.use(http.put('/api/bff/platform/tenants/:id', () => HttpResponse.json({}, { status: 503 })));
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect(await screen.findByText('The tenant could not be created. Try again.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<CreateTenantForm />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
