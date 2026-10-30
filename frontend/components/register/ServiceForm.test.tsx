import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { bffRegistrationState, resetStepSaves, seenStepSaves } from '@/test/msw/handlers/registration';
import { ServiceForm } from './ServiceForm';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

// These flows type through a whole form in one test: the suite's default five seconds is too little on a loaded machine.
vi.setConfig({ testTimeout: 20_000 });

// Registration step 3, describing the service (W25, artboards RegisterFlow2 panels 5 and 6). The
// criteria set here are what advisors filter on, so each answer is checked before it is sent.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

async function open() {
  const view = render(<ServiceForm registrationId={ID} />);
  // The header renders while the registration loads; wait for the loaded controls, not the heading.
  await screen.findByRole('group', { name: 'Category' });
  return view;
}

/** Fills every field of a valid service, so one test can change one answer. */
async function fillValid() {
  await userEvent.click(screen.getByRole('button', { name: 'Urgent community response' }));
  await userEvent.click(screen.getByRole('button', { name: 'Phone' }));
  await userEvent.type(screen.getByLabelText('Phone number for the coordination team to call'), '01305 123456');
  for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']) await userEvent.click(screen.getByRole('button', { name: day }));
  await userEvent.type(screen.getByLabelText('From'), '08:00');
  await userEvent.type(screen.getByLabelText('To'), '18:00');
  await userEvent.click(screen.getByRole('button', { name: 'Frailty' }));
  await userEvent.type(screen.getByLabelText('Youngest age'), '65');
  await userEvent.click(screen.getByRole('button', { name: 'No limit' }));
  await userEvent.click(screen.getByRole('button', { name: 'No exclusions' }));
  await userEvent.type(screen.getByLabelText('Criteria owner (role)'), 'Community matron');
  await userEvent.type(screen.getByLabelText('Owner email'), 'owner@example.test');
  fireEvent.change(screen.getByLabelText('Review criteria by'), { target: { value: '2027-01-31' } });
  await userEvent.click(screen.getByRole('button', { name: 'DT3' }));
  await userEvent.click(screen.getByRole('button', { name: 'DT4' }));
}

beforeEach(() => {
  push.mockClear();
  resetStepSaves();
  bffRegistrationState.view = {
    id: ID,
    status: 'draft',
    serviceName: 'UCR West',
    steps: { location: { fixedSite: true } },
  };
});

describe('ServiceForm: the screen', () => {
  it('shows the service name the shift lead set as read-only, with its hint', async () => {
    await open();
    const name = screen.getByLabelText('Service name');
    expect(name).toHaveValue('UCR West');
    expect(name).toHaveAttribute('readonly');
    expect(name).toHaveAccessibleDescription('The name advisors see, for example “UCR West”');
  });

  it('shows the categories, the referral methods and the coordination team number with its hint', async () => {
    await open();
    const categories = screen.getByRole('group', { name: 'Category' });
    expect(within(categories).getAllByRole('button')).toHaveLength(8);
    expect(screen.getByRole('button', { name: 'Hospital at home or virtual ward' })).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'How can the coordination team refer?' })).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Phone',
      'Clinical record system',
      'Email',
      'e-Referral',
    ]);
    expect(screen.getByLabelText('Phone number for the coordination team to call')).toHaveAccessibleDescription('Staffed while you accept referrals');
  });

  it('shows the "Who it is for" section with its fields and the criteria owner', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 2, name: 'Who it is for' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Needs you accept' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Needs you do not accept' })).toBeInTheDocument();
    expect(screen.getByLabelText('Oldest age')).toBeInTheDocument();
    expect(screen.getByLabelText('Review criteria by')).toHaveAccessibleDescription('Advisors see a flag when this date passes');
    expect(screen.getByLabelText('Anything else advisors should know')).toHaveAttribute('maxlength', '500');
  });
});

describe('ServiceForm: exclusions, ages and districts', () => {
  it('"No exclusions" clears the chosen exclusions, and choosing one clears "No exclusions"', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Suspected fracture' }));
    await userEvent.click(screen.getByRole('button', { name: 'No exclusions' }));
    expect(screen.getByRole('button', { name: 'Suspected fracture' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'No exclusions' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Infection isolation' }));
    expect(screen.getByRole('button', { name: 'No exclusions' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Infection isolation' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('"Add district" takes "dt5" as DT5, and refuses "DT" with the district message', async () => {
    await open();
    await userEvent.type(screen.getByLabelText('Add district'), 'dt5');
    await userEvent.click(screen.getByRole('button', { name: 'Add district' }));
    expect(screen.getByRole('button', { name: 'DT5' })).toHaveAttribute('aria-pressed', 'true');

    await userEvent.type(screen.getByLabelText('Add district'), 'DT');
    await userEvent.click(screen.getByRole('button', { name: 'Add district' }));
    expect(screen.getByText('Enter postcode districts, for example DT4')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'DT' })).not.toBeInTheDocument();
  }, 30_000);

  it('a visiting service with no districts is asked for them; a fixed site is not', async () => {
    bffRegistrationState.view = { ...(bffRegistrationState.view as object), steps: { location: { fixedSite: false } } };
    const first = await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect((await screen.findAllByText('Choose the districts you cover')).length).toBeGreaterThanOrEqual(1);
    first.unmount();

    bffRegistrationState.view = { ...(bffRegistrationState.view as object), steps: { location: { fixedSite: true } } };
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.queryByText('Choose the districts you cover')).not.toBeInTheDocument();
  }, 30_000);
});

describe('ServiceForm: validation and saving', () => {
  it('Continue with three problems shows "There are 3 problems", focused, with links to the fields', async () => {
    await open();
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: 'Urgent community response' }));
    await userEvent.clear(screen.getByLabelText('Phone number for the coordination team to call'));
    await userEvent.type(screen.getByLabelText('Phone number for the coordination team to call'), '0123');
    await userEvent.clear(screen.getByLabelText('Criteria owner (role)'));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    const heading = await screen.findByRole('heading', { name: 'There are 3 problems' });
    const region = heading.closest('[role="alert"]') as HTMLElement;
    expect(region).toHaveFocus();
    expect(within(region).getByRole('link', { name: 'Choose a category' })).toHaveAttribute('href', '#category');
    expect(within(region).getByRole('link', { name: 'Enter who owns the criteria' })).toHaveAttribute('href', '#ownerRole');
    expect(seenStepSaves).toHaveLength(0);
  }, 30_000);

  it('"No limit" sends the oldest age as null, and a valid form PUTs the coded values and goes to step 4', async () => {
    await open();
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/register/${ID}/reporting`));
    expect(seenStepSaves[0]).toMatchObject({
      step: 'service',
      csrf: 'csrf-sample-token',
      body: {
        category: 'urgent-community-response',
        referralMethods: ['phone'],
        spoaPhone: '01305 123456',
        acceptingDays: ['mon', 'tue', 'wed', 'thu', 'fri'],
        acceptingStart: '08:00',
        acceptingEnd: '18:00',
        needs: ['frailty'],
        ageMin: 65,
        ageMax: null,
        noExclusions: true,
        ownerRole: 'Community matron',
        ownerEmail: 'owner@example.test',
        reviewBy: '2027-01-31',
        districts: ['DT3', 'DT4'],
      },
    });
  }, 30_000);

  it('has no axe violations with errors shown', async () => {
    const { container } = await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: /^There (is a problem|are \d+ problems)$/ });
    expect((await runAxe(container)).violations).toEqual([]);
  }, 30_000);
});
