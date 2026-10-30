import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { bffRegistrationState, resetStepSaves, seenStepSaves } from '@/test/msw/handlers/registration';
import { server } from '@/test/msw/server';
import { OrganisationForm } from './OrganisationForm';

// Registration step 1 (W54, artboard RegisterFlow1 panel 3). The invitation's values are shown as
// text and cannot be changed; the answers are the organisation's own.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

async function open() {
  const view = render(<OrganisationForm registrationId={ID} />);
  await screen.findByRole('heading', { level: 1, name: 'Your organisation' });
  return view;
}

function saveAnswer(status: number, body: unknown) {
  server.use(
    http.put(`/api/bff/registrations/${ID}/steps/organisation`, (() =>
      HttpResponse.json(body as Record<string, unknown>, { status })) as HttpResponseResolver),
  );
}

beforeEach(() => {
  push.mockClear();
  resetStepSaves();
  bffRegistrationState.view = {
    id: ID,
    status: 'draft',
    invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
    steps: {},
  };
});

describe('OrganisationForm: the invitation and the screen', () => {
  it('shows the invitation values as text, with no input for any of them', async () => {
    await open();
    expect(screen.getByText('UCR West')).toBeInTheDocument();
    expect(screen.getByText('Sample Community Trust')).toBeInTheDocument();
    expect(screen.getByText('RSA01')).toBeInTheDocument();
    expect(screen.getByText('From your invitation. It cannot be changed.')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /service|organisation|ODS/i })).not.toBeInTheDocument();
  });

  it('shows the step label, the organisation type chips, and the fields with Required or Optional as words', async () => {
    await open();
    expect(screen.getByText('Step 1 of 5 · Organisation')).toBeInTheDocument();
    const types = screen.getByRole('group', { name: 'Organisation type' });
    expect(within(types).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'NHS trust',
      'GP practice',
      'Local authority',
      'Voluntary or independent',
      'Other',
    ]);
    expect(screen.getByLabelText('Part of a larger organisation')).toBeInTheDocument();
    expect(screen.getByLabelText('Your name')).toBeInTheDocument();
    expect(screen.getByLabelText('Your role')).toBeInTheDocument();
    expect(screen.getByLabelText('Contact email or phone')).toHaveAccessibleDescription(
      'For the SPOA to reach your organisation about this registration',
    );
    expect(screen.getAllByText('Required').length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText('Optional')).toBeInTheDocument();
  });

  it('prefills the answers the back end already holds for this step', async () => {
    bffRegistrationState.view = {
      ...(bffRegistrationState.view as object),
      steps: { organisation: { orgType: 'gp-practice', contactName: 'Sample Person', contactEmail: 'contact@example.test' } },
    };
    await open();
    expect(screen.getByRole('button', { name: 'GP practice' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Your name')).toHaveValue('Sample Person');
    expect(screen.getByLabelText('Contact email or phone')).toHaveValue('contact@example.test');
  });

  it('has Continue, Back and Save draft, and a This is not my service link that explains itself', async () => {
    await open();
    expect(screen.getByRole('button', { name: 'Continue' })).toHaveAttribute('data-el', 'REG-STEP1-CONTINUE-BTN');
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', `/register/${ID}/start`);
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveAttribute('data-el', 'REG-STEP1-SAVE-BTN');
    expect(screen.queryByText(/Not your service, or the details are wrong/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'This is not my service' }));
    expect(
      screen.getByText('Not your service, or the details are wrong? Tell the SPOA shift lead. Do not carry on.'),
    ).toBeInTheDocument();
  });
});

describe('OrganisationForm: validation', () => {
  it('shows "There are 4 problems" for an empty Continue, focused, with each message as a link and inline', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    const summary = await screen.findByRole('heading', { name: 'There are 4 problems' });
    const region = summary.closest('[role="alert"]') as HTMLElement;
    expect(region).toHaveFocus();
    for (const message of [
      'Choose the organisation type',
      'Enter your name',
      'Enter your role',
      'Enter an email address or phone number',
    ]) {
      expect(within(region).getByRole('link', { name: message })).toBeInTheDocument();
      expect(screen.getAllByText(message).length).toBeGreaterThanOrEqual(2);
    }
    expect(seenStepSaves).toHaveLength(0);
  });

  it('moves focus to the field when its summary link is pressed', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    const region = (await screen.findByRole('heading', { name: 'There are 4 problems' })).closest('[role="alert"]') as HTMLElement;
    await userEvent.click(within(region).getByRole('link', { name: 'Enter your name' }));
    expect(screen.getByLabelText('Your name')).toHaveFocus();
  });

  it('Save draft with only "Your name" filled sends only that answer and shows no errors', async () => {
    await open();
    await userEvent.type(screen.getByLabelText('Your name'), 'Sample Person');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenStepSaves).toHaveLength(1));
    expect(seenStepSaves[0]).toMatchObject({ id: ID, step: 'organisation', body: { contactName: 'Sample Person' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/problem/)).not.toBeInTheDocument();
  });

  it('puts the errors the back end answers with (422) in the summary and inline', async () => {
    saveAnswer(422, {
      errors: [{ field: 'contact', message: 'Enter a contact email or phone number' }],
    });
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'GP practice' }));
    await userEvent.type(screen.getByLabelText('Your name'), 'Sample Person');
    await userEvent.type(screen.getByLabelText('Your role'), 'Lead');
    await userEvent.type(screen.getByLabelText('Contact email or phone'), 'contact@example.test');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'There is a problem' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Enter a contact email or phone number' })).toHaveAttribute('href', '#contact');
    expect(push).not.toHaveBeenCalled();
  });
});

describe('OrganisationForm: saving', () => {
  it('a valid Continue PUTs the answers with the CSRF header, then goes to step 2', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'NHS trust' }));
    await userEvent.type(screen.getByLabelText('Your name'), 'Sample Person');
    await userEvent.type(screen.getByLabelText('Your role'), 'Lead');
    await userEvent.type(screen.getByLabelText('Contact email or phone'), 'contact@example.test');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/location`));
    expect(seenStepSaves[0]).toMatchObject({
      step: 'organisation',
      csrf: 'csrf-sample-token',
      body: { orgType: 'nhs-trust', contactName: 'Sample Person', contactRole: 'Lead', contact: 'contact@example.test' },
    });
  });

  it('has no axe violations with and without errors shown', async () => {
    const first = await open();
    expect((await runAxe(first.container)).violations).toEqual([]);
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: 'There are 4 problems' });
    expect((await runAxe(first.container)).violations).toEqual([]);
  });
});
