import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import SubmittedPage from './page';

// Submitted: stage 6 of the register frame, a confirmation with no checklist and no help column.

async function open() {
  return render(await SubmittedPage({ params: Promise.resolve({ id: 'REG-SAMPLE-1' }) }));
}

describe('submitted page', () => {
  it('says the registration is submitted, what happens next, and links back to My services', async () => {
    const { container } = await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Submitted. We are checking.' })).toBeInTheDocument();
    expect(
      screen.getByText(/The shift lead will check your details and send a test text to the number you gave\./),
    ).toBeInTheDocument();
    expect(screen.getByText('You will get an email when it is approved, or if something needs changing.')).toBeInTheDocument();
    const back = screen.getByRole('link', { name: 'Back to my services' });
    expect(back).toHaveAttribute('href', '/register/services');
    expect(back).toHaveAttribute('data-el', 'REG-SUBMITTED-BACK-BTN');
    expect((await runAxe(container)).violations).toEqual([]);
  });

  it('lists what happens next: submitted, checks, a test text, live on the board', async () => {
    await open();
    const steps = within(screen.getByRole('list')).getAllByRole('listitem').map((li) => li.textContent);
    expect(steps).toEqual([
      expect.stringMatching(/^Submitted/),
      expect.stringMatching(/^Checks\./),
      expect.stringMatching(/^A test text/),
      expect.stringMatching(/^You are live/),
    ]);
  });

  it('does not invent a review time or a submission time', async () => {
    await open();
    expect(screen.queryByText(/working day/)).toBeNull();
    expect(screen.queryByText(/today/i)).toBeNull();
  });

  it('keeps Save and come back later out of a finished registration and hides the checklist', async () => {
    await open();
    expect(screen.queryByRole('link', { name: 'Save and come back later' })).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Your registration' })).toBeNull();
  });
});
