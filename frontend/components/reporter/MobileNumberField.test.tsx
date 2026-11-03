import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { MOBILE_ERROR, MobileNumberField } from './MobileNumberField';

// Artboard B7 (3): a bold label over a 54px field. The error says what is wrong in words and a shape.

describe('MobileNumberField', () => {
  it('is a telephone field named by its label', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MobileNumberField label="Cover mobile number" value="" onChange={onChange} />);
    const input = screen.getByLabelText('Cover mobile number');
    expect(input).toHaveAttribute('type', 'tel');
    expect(input).toHaveAttribute('inputmode', 'tel');
    await user.type(input, '0');
    expect(onChange).toHaveBeenCalledWith('0');
  });

  it('says Required when it is, and sets the required attribute', () => {
    render(<MobileNumberField label="Cover mobile number" value="" onChange={() => {}} required />);
    expect(screen.getByText('Required')).toBeInTheDocument();
    expect(screen.getByLabelText('Cover mobile number')).toBeRequired();
  });

  it('is marked valid with no error text until there is an error', () => {
    const { container } = render(<MobileNumberField label="Cover mobile number" value="" onChange={() => {}} dataEl="PHONE" />);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(container.querySelector('[data-el="PHONE"]')).not.toHaveAttribute('data-invalid');
  });

  it('shows an error as an alert with a warning shape, tied to the field, and marks the field invalid', async () => {
    const { container } = render(<MobileNumberField label="Cover mobile number" value="12" onChange={() => {}} error={MOBILE_ERROR} dataEl="PHONE" />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(MOBILE_ERROR);
    expect(alert.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    const input = screen.getByLabelText('Cover mobile number');
    expect(input).toBeInvalid();
    expect(input).toHaveAccessibleDescription(MOBILE_ERROR);
    expect(container.querySelector('[data-el="PHONE"]')).toHaveAttribute('data-invalid', 'true');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
