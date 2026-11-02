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
  const values: Record<string, string> = { 'Tenant id': 'trust-d', 'Display name': 'Sample Area D', 'Legal name': 'Sample Area D Organisation', 'ODS code': 'RZZ03', ...over };
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

  it('searches the NHS directory by name, and fills the organisation from the record the operator picks', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/bff/platform/ods', ({ request }) => {
        expect(new URL(request.url).searchParams.get('name')).toBe('ardleigh surgery');
        return HttpResponse.json({ results: [{ code: 'F81044', name: 'THE ARDLEIGH SURGERY', postcode: 'CO7 7LD', primaryRole: 'RO177', status: 'Active' }] });
      }),
      http.get('/api/bff/platform/ods/F81044', () =>
        HttpResponse.json({
          record: {
            code: 'F81044', name: 'THE ARDLEIGH SURGERY', status: 'Active', postcode: 'CO7 7LD', primaryRole: 'RO177',
            roles: [{ id: 'RO177', name: 'PRESCRIBING COST CENTRE', primary: true }, { id: 'RO76', name: 'GP PRACTICE', primary: false }],
            links: [{ relationship: 'RE4', code: '06T', name: 'NHS ESSEX ICB - 06T', role: 'RO98' }],
            lastChangedAt: '2025-01-01', suggestedOrganisationType: 'gp-practice',
          },
        }),
      ),
    );
    render(<CreateTenantForm />);
    await user.type(screen.getByLabelText('Organisation’s name'), 'ardleigh surgery');
    await user.click(screen.getByRole('button', { name: 'Search the NHS directory' }));
    await user.click(await screen.findByRole('button', { name: /Use THE ARDLEIGH SURGERY \(F81044/ }));
    const record = await screen.findByText(/Active links:/);
    expect(record).toHaveTextContent('NHS ESSEX ICB - 06T (06T)');
    // Once matched, the record's fields are not typed in again: the card says what it filled.
    expect(screen.queryByLabelText('Display name')).toBeNull();
    expect(screen.queryByLabelText('ODS code')).toBeNull();
    expect(screen.getByText(/Organisation type: GP practice · Country: GB · Time zone: Europe\/London/)).toBeInTheDocument();
    expect(screen.getByLabelText('Tenant id')).toHaveValue('the-ardleigh-surgery');
  });

  it('refuses an NHS trust, ICB or GP practice with no ODS code, and sends nothing', async () => {
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user, { 'ODS code': '' });
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect((await screen.findAllByText(/An NHS trust, ICB or GP practice needs its ODS code/)).length).toBeGreaterThan(0);
    expect(seenOperatorWrites).toHaveLength(0);
  });

  it('looks the directory id up from the domain, fills it in for the operator to check, and says what it found', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/bff/platform/directory-lookup', ({ request }) => {
        expect(new URL(request.url).searchParams.get('domain')).toBe('example.nhs.uk');
        return HttpResponse.json({ domain: 'example.nhs.uk', directoryId: 'c5901e0b-8d43-4ae8-97c3-ca6c52573a33' });
      }),
    );
    render(<CreateTenantForm />);
    await user.type(screen.getByLabelText('Organisation’s domain'), 'example.nhs.uk');
    await user.click(screen.getByRole('button', { name: 'Look up directory id' }));
    const card = await screen.findByText('Entra directory');
    expect(card.closest('[data-el="OP-CREATE-DIRECTORY-CARD"]')).toHaveTextContent('c5901e0b-8d43-4ae8-97c3-ca6c52573a33');
    expect(screen.queryByLabelText('Directory id')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Choose another directory' }));
    expect(screen.getByLabelText('Directory id')).toHaveValue('');
  });

  it('says so when a domain has no directory, and fills nothing', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'nowhere.example', directoryId: null })));
    render(<CreateTenantForm />);
    await user.type(screen.getByLabelText('Organisation’s domain'), 'nowhere.example');
    await user.click(screen.getByRole('button', { name: 'Look up directory id' }));
    expect(await screen.findByRole('status')).toHaveTextContent('No directory was found for nowhere.example');
    expect(screen.getByLabelText('Directory id')).toHaveValue('');
  });

  it('is in three parts: the organisation, the directory (saved as waiting) and who gets which role', () => {
    render(<CreateTenantForm />);
    expect(screen.getByRole('group', { name: '1 The organisation' })).toBeInTheDocument();
    const directory = screen.getByRole('group', { name: '2 Entra directory' });
    expect(within(directory).getByLabelText('Directory id')).toHaveValue('');
    expect(within(directory).getByText('Waiting: you confirm it on the organisation’s page after it is created')).toBeInTheDocument();
    const roles = screen.getByRole('group', { name: '3 Who gets which role' });
    expect(within(roles).getByText(/No group is mapped yet/)).toBeInTheDocument();
    expect(within(roles).getByText(/cannot be given the administrator’s role/)).toBeInTheDocument();
  });

  it('creates a tenant with a directory id and a group-to-role mapping, and says the directory is waiting', async () => {
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user);
    await user.type(screen.getByLabelText('Directory id'), '00000000-0000-4000-8000-000000000000');
    await user.click(screen.getByRole('button', { name: 'Add a group' }));
    await user.click(screen.getByRole('button', { name: 'Add another group' }));
    const groups = screen.getAllByLabelText('Group object id');
    await user.type(groups[0]!, '11111111-1111-4111-8111-111111111111');
    await user.type(groups[1]!, '22222222-2222-4222-8222-222222222222');
    await user.selectOptions(screen.getAllByRole('combobox', { name: 'Role' })[1]!, 'clinical');
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(seenOperatorWrites[0]!.body).toEqual({
      displayName: 'Sample Area D',
      legalName: 'Sample Area D Organisation',
      organisationType: 'nhs-trust',
      odsCode: 'RZZ03',
      countryCode: 'GB',
      timeZone: 'Europe/London',
      directoryId: '00000000-0000-4000-8000-000000000000',
      roleMappings: [
        { groupObjectId: '11111111-1111-4111-8111-111111111111', role: 'advisor' },
        { groupObjectId: '22222222-2222-4222-8222-222222222222', role: 'clinical' },
      ],
    });
    const done = await screen.findByRole('status');
    expect(done).toHaveTextContent('Their Microsoft account is waiting for you to confirm it.');
    expect(done).toHaveTextContent('2 groups are mapped to roles.');
  });

  it('offers no administrator role to a group, and a row can be removed', async () => {
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await user.click(screen.getByRole('button', { name: 'Add a group' }));
    const options = within(screen.getByRole('combobox', { name: 'Role' })).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['Advisor', 'Clinical lead', 'Shift lead', 'Criteria owner', 'Planning', 'Audit']);
    await user.click(screen.getByRole('button', { name: 'Remove group 1' }));
    expect(screen.queryByLabelText('Group object id')).not.toBeInTheDocument();
  });

  it('refuses a directory id or a group id that is not a directory id, in words, and sends nothing', async () => {
    const user = userEvent.setup();
    render(<CreateTenantForm />);
    await fill(user);
    await user.type(screen.getByLabelText('Directory id'), 'not-a-guid');
    await user.click(screen.getByRole('button', { name: 'Add a group' }));
    await user.type(screen.getByLabelText('Group object id'), 'also-not');
    await user.click(screen.getByRole('button', { name: 'Create tenant' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('There are 2 problems');
    expect(screen.getByRole('link', { name: /Directory id: enter it as a directory id/ })).toHaveAttribute('href', '#directory-id');
    expect(screen.getByRole('link', { name: /Group 1: enter the group object id/ })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
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
