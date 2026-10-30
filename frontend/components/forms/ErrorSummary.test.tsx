import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ErrorSummary } from './ErrorSummary';

// The shared error summary for the registration steps (W54). Each message links to its field and the
// summary takes focus when it appears, so a screen reader hears what is wrong first.

const TWO = [
  { field: 'contactName', message: 'Enter your name' },
  { field: 'orgType', message: 'Choose the organisation type' },
];

describe('ErrorSummary', () => {
  it('says "There is a problem" for one error', () => {
    render(<ErrorSummary errors={[TWO[0]!]} />);
    expect(screen.getByRole('heading', { name: 'There is a problem' })).toBeInTheDocument();
  });

  it('says "There are N problems" for N errors, and lists each message as a link to its field', () => {
    render(<ErrorSummary errors={TWO} />);
    expect(screen.getByRole('heading', { name: 'There are 2 problems' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Enter your name' })).toHaveAttribute('href', '#contactName');
    expect(screen.getByRole('link', { name: 'Choose the organisation type' })).toHaveAttribute('href', '#orgType');
  });

  it('is an alert that takes focus when it appears', () => {
    render(<ErrorSummary errors={TWO} />);
    const region = screen.getByRole('alert');
    expect(region).toHaveAttribute('tabindex', '-1');
    expect(region).toHaveFocus();
  });

  it('moves focus to the field when its link is pressed', async () => {
    render(
      <>
        <ErrorSummary errors={TWO} />
        <input id="contactName" aria-label="Your name" />
        <fieldset id="orgType" tabIndex={-1}>
          <legend>Organisation type</legend>
        </fieldset>
      </>,
    );
    await userEvent.click(screen.getByRole('link', { name: 'Enter your name' }));
    expect(screen.getByLabelText('Your name')).toHaveFocus();
    await userEvent.click(screen.getByRole('link', { name: 'Choose the organisation type' }));
    expect(document.getElementById('orgType')).toHaveFocus();
  });

  it('renders nothing when there are no errors', () => {
    const { container } = render(<ErrorSummary errors={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ErrorSummary errors={TWO} />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
