import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RegistrationOverview } from './RegistrationOverview';

describe('RegistrationOverview', () => {
  it('shows a failing automatic check with its warning and the action to take', async () => {
    const { container } = render(<RegistrationOverview id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR East' })).toBeInTheDocument();
    expect(screen.getByText('Registered by Sample Person, Duty manager')).toBeInTheDocument();
    expect(screen.getByText('Criteria owner email is not an organisation address')).toBeInTheDocument();
    expect(screen.getByText('Ask for an organisation address')).toBeInTheDocument();
    expect(screen.getByText('ODS code found, active, NHS trust')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('reads check 4 as "Opens when 1 to 3 are done" and links the first check to the call-back page', async () => {
    render(<RegistrationOverview id="r1" />);
    expect(await screen.findByText('Opens when 1 to 3 are done')).toBeInTheDocument();
    const start = screen.getByRole('link', { name: 'Start with the call-back' });
    expect(start).toHaveAttribute('href', '/lead/registrations/r1?step=callback');
    expect(start).toHaveAttribute('data-el', 'LEAD-REG-START-CALLBACK-BTN');
  });
});
