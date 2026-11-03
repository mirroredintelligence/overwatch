import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Tour, type TourStep } from './Tour';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Tour: the welcome step', () => {
  it('shows the one-minute promise with no account needed, and starts the tour', async () => {
    render(<Tour initialStep="welcome" />);

    expect(screen.getByRole('heading', { name: 'See how Overwatch works for you' })).toBeInTheDocument();
    expect(screen.getByText('One minute. No account needed.')).toBeInTheDocument();
    expect(screen.getByText('Step 1 of 6')).toBeInTheDocument();
    expect(screen.getByText('Welcome')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Start the tour' }));
    expect(screen.getByRole('heading', { name: 'Which is you?' })).toBeInTheDocument();
  });
});

describe('Tour: picking a role and what changes', () => {
  it('keeps Next disabled until a role is picked, then shows the advisor lists', async () => {
    render(<Tour initialStep="role" />);

    const nextButton = screen.getByRole('button', { name: 'Next' });
    expect(nextButton).toBeDisabled();

    await userEvent.click(screen.getByRole('radio', { name: 'I take calls as an advisor' }));
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(screen.getByRole('heading', { name: 'For call advisors' })).toBeInTheDocument();
    const today = screen.getByRole('list', { name: 'Today' });
    expect(within(today).getByText('Phone several services to find space')).toBeInTheDocument();
    const withOverwatch = screen.getByRole('list', { name: 'With Overwatch' });
    expect(within(withOverwatch).getByText('Request a booking by text and move on')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try a practice call' })).toBeInTheDocument();
  });

  it('offers the five role cards as one radio group, with the step count', () => {
    render(<Tour initialStep="role" />);

    expect(screen.getByText('Step 2 of 6')).toBeInTheDocument();
    expect(screen.getByText('Your role')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Which is you?' })).toBeInTheDocument();
    expect(screen.getAllByRole('radio')).toHaveLength(5);
    expect(screen.getByRole('radio', { name: 'I report capacity for a service' })).toHaveAttribute('name', 'tour-role');
  });
});

describe('Tour: what changes for each role (TourRoles)', () => {
  it.each([
    ['lead', 'Invite a reporter', '/lead/reporters/invite'],
    ['clinical', 'Go on duty', '/clinical'],
    ['exec', 'Choose my alerts', '/planning/setup'],
  ] as const)('the %s screen offers its action at its page, and Skip, besides Next', (role, action, href) => {
    render(<Tour initialStep="changes" initialRole={role} />);

    expect(screen.getByRole('link', { name: action })).toHaveAttribute('href', href);
    expect(screen.getByRole('link', { name: 'Skip' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument();
  });

  it('the reporter screen has Next and no Skip, and its action is the practice step', async () => {
    render(<Tour initialStep="changes" initialRole="reporter" />);

    expect(screen.getByText('Step 3 of 6')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Your day, before and after' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Skip' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Try a practice update' }));
    expect(screen.getByRole('heading', { name: 'Answer a practice prompt' })).toBeInTheDocument();
  });
});

describe('Tour: how it works and the first week', () => {
  it('numbers the three steps of how it works', () => {
    render(<Tour initialStep="how" />);

    expect(screen.getByText('Step 4 of 6')).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'How it works' });
    expect(within(steps).getAllByRole('listitem')).toHaveLength(3);
    expect(within(steps).getByText('The coordination team sees it at once')).toBeInTheDocument();
  });

  it('lists the first week and says what Friday shows, with Go to my app', () => {
    render(<Tour initialStep="week" />);

    expect(screen.getByText('Step 6 of 6')).toBeInTheDocument();
    expect(screen.getByText('Set up your phone')).toBeInTheDocument();
    expect(screen.getByText('On Friday we show you what you saved: updates sent and phone calls avoided.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to my app' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: 'Start again' })).toHaveAttribute('href', '/tour?step=welcome');
  });
});

describe('Tour: practice', () => {
  it('makes no network request, says nothing is sent, and shows Practice done', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<Tour initialStep="practice" initialRole="reporter" />);

    expect(screen.getByText('Step 5 of 6')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Answer a practice prompt' })).toBeInTheDocument();
    expect(screen.getByText('Nothing is sent. Your answer only changes what the screen says.')).toBeInTheDocument();
    expect(screen.getByText('Sample data')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still right' }));

    expect(screen.getByText('Practice done')).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('Tour: the reporter screens', () => {
  it('says "[x] minutes" for a phone call and never states a number of minutes saved', () => {
    render(<Tour initialStep="changes" initialRole="reporter" />);

    expect(screen.getByText('A phone call today takes [x] minutes. We measure it in the pilot.')).toBeInTheDocument();
    expect(screen.queryByText(/minutes? saved/i)).toBeNull();
  });
});

describe('Tour: storage', () => {
  it('still runs when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<Tour initialStep="welcome" />);

    await userEvent.click(screen.getByRole('button', { name: 'Start the tour' }));

    expect(screen.getByRole('heading', { name: 'Which is you?' })).toBeInTheDocument();
  });
});

describe('Tour: moving through the steps', () => {
  it('moves Next and Back in the Tour steps bar, and moves focus to the new step heading', async () => {
    render(<Tour initialStep="welcome" />);

    await userEvent.click(screen.getByRole('button', { name: 'Start the tour' }));
    const heading = screen.getByRole('heading', { name: 'Which is you?' });
    await waitFor(() => expect(heading).toHaveFocus());

    const steps = screen.getByRole('navigation', { name: 'Tour steps' });
    await userEvent.click(within(steps).getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('heading', { name: 'See how Overwatch works for you' })).toBeInTheDocument();
  });

  it('offers a Skip link in the top bar that goes to the home page', () => {
    render(<Tour initialStep="how" />);

    expect(screen.getByRole('link', { name: 'Skip' })).toHaveAttribute('href', '/');
  });

  it.each<TourStep>(['welcome', 'role', 'changes', 'how', 'practice', 'week'])('passes vitest-axe on the %s step', async (step) => {
    const { container } = render(<Tour initialStep={step} initialRole="reporter" />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
