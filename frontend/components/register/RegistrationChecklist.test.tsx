import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RegistrationChecklist } from './RegistrationChecklist';

const LABELS = ['Organisation', 'Location', 'Service', 'Capacity reporting', 'Review'];

function words() {
  return within(screen.getByRole('navigation', { name: 'Your registration' }))
    .getAllByRole('link')
    .map((link) => link.textContent);
}

describe('RegistrationChecklist', () => {
  it('is a navigation of five links to the steps of this registration, in order', () => {
    render(<RegistrationChecklist registrationId="REG-1" stage={1} />);
    const links = within(screen.getByRole('navigation', { name: 'Your registration' })).getAllByRole('link');
    expect(links).toHaveLength(5);
    LABELS.forEach((label, i) => expect(links[i]).toHaveTextContent(label));
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      '/register/REG-1/organisation',
      '/register/REG-1/location',
      '/register/REG-1/service',
      '/register/REG-1/reporting',
      '/register/REG-1/review',
    ]);
  });

  it('marks the current step with aria-current="step" and no other', () => {
    render(<RegistrationChecklist registrationId="REG-1" stage={3} />);
    const current = screen.getAllByRole('link').filter((l) => l.getAttribute('aria-current') === 'step');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent('Service');
  });

  it('has no current step on the start page', () => {
    render(<RegistrationChecklist registrationId="REG-1" stage={0} />);
    expect(screen.getAllByRole('link').some((l) => l.hasAttribute('aria-current'))).toBe(false);
  });

  it('says each state in words: done before, in progress here, not started after', () => {
    render(<RegistrationChecklist registrationId="REG-1" stage={3} />);
    expect(words()).toEqual([
      'OrganisationComplete',
      'LocationComplete',
      'ServiceIn progress',
      'Capacity reportingNot started',
      'ReviewNot started',
    ]);
  });

  it('shows the states it is given, including Needs attention', () => {
    render(<RegistrationChecklist registrationId="REG-1" stage={5} states={{ 3: 'needs-attention' }} />);
    expect(words()).toEqual([
      'OrganisationComplete',
      'LocationComplete',
      'ServiceNeeds attention',
      'Capacity reportingComplete',
      'ReviewIn progress',
    ]);
  });

  it('says Submitted on every entry once the registration is submitted', () => {
    render(<RegistrationChecklist registrationId="REG-1" stage={6} />);
    expect(words().every((w) => w?.endsWith('Submitted'))).toBe(true);
  });

  it('encodes the id in the links', () => {
    render(<RegistrationChecklist registrationId="a b/c" stage={1} />);
    expect(screen.getByRole('link', { name: /Organisation/ })).toHaveAttribute('href', '/register/a%20b%2Fc/organisation');
  });

  it('has no axe violations', async () => {
    const { container } = render(<RegistrationChecklist registrationId="REG-1" stage={2} />);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
