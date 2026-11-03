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

// Registration step 3, describing the service (Reg board stage 3, RP2 board). "The service" is open; "Who it is
// for", "Criteria owner and review date" and "Area you cover" are rows that say their answer when closed and flag
// what is missing. The criteria set here are what advisors filter on, so each answer is checked before it is sent.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';
const WHO = /^Who it is for/;
const OWNER = /^Criteria owner and review date/;
const AREA = /^Area you cover/;

async function open() {
  const view = render(<ServiceForm registrationId={ID} />);
  // The header renders while the registration loads; wait for the loaded controls, not the heading.
  await screen.findByRole('group', { name: 'Category' });
  return view;
}

/** Opens a disclosure row if it is closed. */
async function openRow(name: RegExp) {
  const row = screen.getByRole('button', { name });
  if (row.getAttribute('aria-expanded') !== 'true') await userEvent.click(row);
}

/** Fills every field of a valid service, so one test can change one answer. */
async function fillValid() {
  await userEvent.click(screen.getByRole('button', { name: 'Urgent community response' }));
  await userEvent.click(screen.getByRole('button', { name: 'Phone' }));
  await userEvent.type(screen.getByLabelText('Phone for the shift lead to call'), '01305 123456');
  for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']) await userEvent.click(screen.getByRole('button', { name: day }));
  await userEvent.type(screen.getByLabelText('From'), '08:00');
  await userEvent.type(screen.getByLabelText('To'), '18:00');
  await openRow(WHO);
  await userEvent.click(screen.getByRole('button', { name: 'Frailty' }));
  await userEvent.type(screen.getByLabelText('Youngest age'), '65');
  await userEvent.click(screen.getByRole('button', { name: 'No limit' }));
  await userEvent.click(screen.getByRole('button', { name: 'No exclusions' }));
  await openRow(OWNER);
  await userEvent.type(screen.getByLabelText('Criteria owner (role)'), 'Community matron');
  await userEvent.type(screen.getByLabelText('Owner email'), 'owner@example.test');
  fireEvent.change(screen.getByLabelText('Review criteria by'), { target: { value: '2027-01-31' } });
  await openRow(AREA);
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
  it('sits in the register frame, with the service in the top bar and Service current in the checklist', async () => {
    await open();
    expect(screen.getByText('Step 3 of 5 · Service')).toBeInTheDocument();
    const stage = screen.getByRole('region', { name: 'Current step' });
    expect(within(stage).getByRole('heading', { level: 1, name: 'Describe the service' })).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByText('UCR West · invited by your shift lead')).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Save and come back later' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Your registration' });
    expect(within(nav).getByRole('link', { name: /^Service/ })).toHaveAttribute('aria-current', 'step');
  });

  it('shows "The service" open: the name as read-only with its hint, the phone and the category', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 2, name: 'The service' })).toBeInTheDocument();
    const name = screen.getByLabelText('Service name');
    expect(name).toHaveValue('UCR West');
    expect(name).toHaveAttribute('readonly');
    expect(name).toHaveAccessibleDescription('The name advisors see, for example “UCR West”');
    expect(screen.getByLabelText('Phone for the shift lead to call')).toHaveAccessibleDescription('Staffed while you accept referrals');
    const categories = screen.getByRole('group', { name: 'Category' });
    expect(within(categories).getAllByRole('button')).toHaveLength(8);
    expect(screen.getByRole('button', { name: 'Hospital at home or virtual ward' })).toBeInTheDocument();
  });

  it('shows the referral methods and the days and hours in the open section', async () => {
    await open();
    expect(within(screen.getByRole('group', { name: 'How can the coordination team refer?' })).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Phone',
      'Clinical record system',
      'Email',
      'e-Referral',
    ]);
    expect(screen.getByRole('group', { name: 'Days you accept referrals' })).toBeInTheDocument();
    expect(screen.getByLabelText('From')).toBeInTheDocument();
    expect(screen.getByLabelText('To')).toBeInTheDocument();
  });

  it('has three closed rows, each a button that says whether it is open', async () => {
    await open();
    for (const name of [WHO, OWNER, AREA]) expect(screen.getByRole('button', { name })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('heading', { level: 2, name: 'Who it is for' })).not.toBeInTheDocument();
  });

  it('opens "Who it is for" to its fields and the criteria owner row to the owner and the review date', async () => {
    await open();
    await openRow(WHO);
    expect(screen.getByRole('button', { name: WHO })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('group', { name: 'Needs you accept' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Needs you do not accept' })).toBeInTheDocument();
    expect(screen.getByLabelText('Oldest age')).toBeInTheDocument();
    await openRow(OWNER);
    expect(screen.getByLabelText('Review criteria by')).toHaveAccessibleDescription('Advisors see a flag when this date passes');
    expect(screen.getByLabelText('Anything else advisors should know')).toHaveAttribute('maxlength', '500');
  });
});

describe('ServiceForm: what a closed row says', () => {
  it('flags "Needs a review date" until the owner and the date are given, then says them', async () => {
    await open();
    expect(screen.getByRole('button', { name: OWNER })).toHaveAccessibleName(/Needs an owner and a review date/);
    await openRow(OWNER);
    await userEvent.type(screen.getByLabelText('Criteria owner (role)'), 'Community matron');
    await userEvent.type(screen.getByLabelText('Owner email'), 'owner@example.test');
    expect(screen.getByRole('button', { name: OWNER })).toHaveAccessibleName(/Needs a review date/);
    fireEvent.change(screen.getByLabelText('Review criteria by'), { target: { value: '2027-01-31' } });
    const row = screen.getByRole('button', { name: OWNER });
    expect(row).toHaveAccessibleName(/Community matron · review by 31 Jan 2027/);
    expect(row).not.toHaveAccessibleName(/Needs/);
  });

  it('says the needs, the ages and the exclusions of "Who it is for" when it is closed', async () => {
    await open();
    expect(screen.getByRole('button', { name: WHO })).toHaveAccessibleName(/Needs answers/);
    await openRow(WHO);
    await userEvent.click(screen.getByRole('button', { name: 'Frailty' }));
    await userEvent.click(screen.getByRole('button', { name: 'Dementia' }));
    await userEvent.type(screen.getByLabelText('Youngest age'), '18');
    await userEvent.click(screen.getByRole('button', { name: 'No limit' }));
    await userEvent.click(screen.getByRole('button', { name: 'Suspected fracture' }));
    await userEvent.click(screen.getByRole('button', { name: 'Infection isolation' }));
    expect(screen.getByRole('button', { name: WHO })).toHaveAccessibleName(/Frailty, Dementia · age 18\+ · 2 exclusions/);
  });

  it('says the districts of "Area you cover", and asks for them when the service visits patients', async () => {
    await open();
    await openRow(AREA);
    await userEvent.click(screen.getByRole('button', { name: 'DT1' }));
    await userEvent.click(screen.getByRole('button', { name: 'DT4' }));
    expect(screen.getByRole('button', { name: AREA })).toHaveAccessibleName(/DT1, DT4/);
  });

  it('flags the area as needed for a visiting service', async () => {
    bffRegistrationState.view = { ...(bffRegistrationState.view as object), steps: { location: { fixedSite: false } } };
    await open();
    expect(screen.getByRole('button', { name: AREA })).toHaveAccessibleName(/Needs an area/);
  });
});

describe('ServiceForm: exclusions, ages and districts', () => {
  it('"No exclusions" clears the chosen exclusions, and choosing one clears "No exclusions"', async () => {
    await open();
    await openRow(WHO);
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
    await openRow(AREA);
    await userEvent.type(screen.getByLabelText('Add district'), 'dt5');
    await userEvent.click(screen.getByRole('button', { name: 'Add district' }));
    expect(screen.getByRole('button', { name: 'DT5' })).toHaveAttribute('aria-pressed', 'true');

    await userEvent.type(screen.getByLabelText('Add district'), 'DT');
    await userEvent.click(screen.getByRole('button', { name: 'Add district' }));
    expect(screen.getByText('Enter postcode districts, for example DT4')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'DT' })).not.toBeInTheDocument();
  }, 30_000);

  it('a visiting service with no districts is asked for them, and its row opens; a fixed site is not asked', async () => {
    bffRegistrationState.view = { ...(bffRegistrationState.view as object), steps: { location: { fixedSite: false } } };
    const first = await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect((await screen.findAllByText('Choose the districts you cover')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('button', { name: AREA })).toHaveAttribute('aria-expanded', 'true');
    first.unmount();

    bffRegistrationState.view = { ...(bffRegistrationState.view as object), steps: { location: { fixedSite: true } } };
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.queryByText('Choose the districts you cover')).not.toBeInTheDocument();
  }, 30_000);
});

describe('ServiceForm: validation and saving', () => {
  it('Continue with three problems shows "3 problems to fix", focused, with links to the fields', async () => {
    await open();
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: 'Urgent community response' }));
    await userEvent.clear(screen.getByLabelText('Phone for the shift lead to call'));
    await userEvent.type(screen.getByLabelText('Phone for the shift lead to call'), '0123');
    await userEvent.clear(screen.getByLabelText('Criteria owner (role)'));
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    const heading = await screen.findByRole('heading', { name: '3 problems to fix' });
    const region = heading.closest('[role="alert"]') as HTMLElement;
    expect(region).toHaveFocus();
    expect(region).toHaveTextContent('▲');
    expect(within(region).getByRole('link', { name: 'Choose a category' })).toHaveAttribute('href', '#category');
    expect(within(region).getByRole('link', { name: 'Enter who owns the criteria' })).toHaveAttribute('href', '#ownerRole');
    expect(seenStepSaves).toHaveLength(0);
  }, 30_000);

  it('a problem opens the row that holds its field, and marks Service as needing attention in the checklist', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: /problems to fix$/ });
    for (const name of [WHO, OWNER]) expect(screen.getByRole('button', { name })).toHaveAttribute('aria-expanded', 'true');
    const nav = screen.getByRole('navigation', { name: 'Your registration' });
    expect(within(nav).getByRole('link', { name: /^Service/ })).toHaveTextContent('Needs attention');
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

  it('Save draft sends the step without going on', async () => {
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenStepSaves.length).toBeGreaterThan(0));
    expect(push).not.toHaveBeenCalled();
  });

  it('has no axe violations with errors shown', async () => {
    const { container } = await open();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('heading', { name: /^(1 problem|\d+ problems) to fix$/ });
    expect((await runAxe(container)).violations).toEqual([]);
  }, 30_000);
});
