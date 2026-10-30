import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ErrorSummary } from './ErrorSummary';

function Field({ id, label }: { id: string; label: string }) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <input id={id} />
    </>
  );
}

describe('ErrorSummary', () => {
  const errors = [
    { field: 'lead-name', message: 'Enter the service name' },
    { field: 'lead-mobile', message: 'Enter a UK mobile number, like 07700 900456' },
  ];

  it('says how many problems there are and links each one to its field', () => {
    render(
      <>
        <ErrorSummary errors={errors} />
        <Field id="lead-name" label="Service name" />
        <Field id="lead-mobile" label="Mobile number" />
      </>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('There are 2 problems');
    expect(screen.getByRole('link', { name: 'Enter the service name' })).toHaveAttribute('href', '#lead-name');
    expect(screen.getByRole('link', { name: 'Enter a UK mobile number, like 07700 900456' })).toHaveAttribute(
      'href',
      '#lead-mobile',
    );
  });

  it('uses the singular for one problem', () => {
    render(<ErrorSummary errors={[errors[0]]} />);
    expect(screen.getByRole('alert')).toHaveTextContent('There is 1 problem');
  });

  it('moves focus to the field a link names', async () => {
    render(
      <>
        <ErrorSummary errors={errors} />
        <Field id="lead-name" label="Service name" />
        <Field id="lead-mobile" label="Mobile number" />
      </>,
    );
    await userEvent.click(screen.getByRole('link', { name: 'Enter the service name' }));
    expect(screen.getByLabelText('Service name')).toHaveFocus();
  });

  it('renders nothing when there are no errors', () => {
    const { container } = render(<ErrorSummary errors={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ErrorSummary errors={errors} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
