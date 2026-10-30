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

describe('Tour: picking a role and what changes', () => {
  it('keeps Continue disabled until a role is picked, then shows the advisor lists', async () => {
    render(<Tour initialStep="role" />);

    const continueButton = screen.getByRole('button', { name: 'Continue' });
    expect(continueButton).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'I take calls as an SPOA advisor' }));
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(screen.getByRole('heading', { name: 'For call advisors' })).toBeInTheDocument();
    const today = screen.getByRole('list', { name: 'Today' });
    expect(within(today).getByText('Phone several services to find space')).toBeInTheDocument();
    const withDiucs = screen.getByRole('list', { name: 'With DIUCS' });
    expect(within(withDiucs).getByText('Request a booking by text and move on')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try a practice call' })).toBeInTheDocument();
  });
});

describe('Tour: practice', () => {
  it('makes no network request and shows Practice done', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<Tour initialStep="practice" initialRole="reporter" />);

    expect(screen.getByText('Practice. Nothing is sent.')).toBeInTheDocument();
    expect(screen.getByText('Sample data')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, still 3' }));

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

    await userEvent.click(screen.getByRole('button', { name: 'Take the 1-minute tour' }));

    expect(screen.getByRole('heading', { name: 'What do you do?' })).toBeInTheDocument();
  });
});

describe('Tour: moving through the steps', () => {
  it('moves Next and Back, and moves focus to the new step heading', async () => {
    render(<Tour initialStep="welcome" />);

    await userEvent.click(screen.getByRole('button', { name: 'Take the 1-minute tour' }));
    const heading = screen.getByRole('heading', { name: 'What do you do?' });
    await waitFor(() => expect(heading).toHaveFocus());

    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('heading', { name: 'Less chasing. Faster answers.' })).toBeInTheDocument();
  });

  it.each<TourStep>(['welcome', 'role', 'changes', 'how', 'practice', 'week'])('passes vitest-axe on the %s step', async (step) => {
    const { container } = render(<Tour initialStep={step} initialRole="reporter" />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
