import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import StartPage from './page';

// Register a service: the start page, stage 0 of the register frame (Reg board). It lists what to have ready
// and links on to step 1, inside the checklist and top bar every register step shares.

async function open(id = 'REG-SAMPLE-1') {
  return render(await StartPage({ params: Promise.resolve({ id }) }));
}

describe('registration start page', () => {
  it('shows the heading, the time it takes and the five things to have ready', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Register your service' })).toBeInTheDocument();
    const stage = screen.getByRole('region', { name: 'Current step' });
    expect(within(stage).getByText('It takes about 10 minutes. Have these ready:')).toBeInTheDocument();
    const items = within(within(stage).getByRole('list')).getAllByRole('listitem').map((item) => item.textContent);
    expect(items).toEqual([
      '1Organisation name and ODS code',
      '2The address of the site, or the area you cover',
      '3A phone number the shift lead can call',
      '4Who owns your criteria, and when they are next reviewed',
      '5A mobile number or email for capacity updates',
    ]);
  });

  it('links Start to the organisation step of this registration', async () => {
    await open('REG-SAMPLE-1');
    const start = screen.getByRole('link', { name: 'Start' });
    expect(start).toHaveAttribute('href', '/register/REG-SAMPLE-1/organisation');
    expect(start).toHaveAttribute('data-el', 'REG-START-BTN');
  });

  it('has Save and come back later in the top bar, which returns to sign-in with the note', async () => {
    await open();
    const later = within(screen.getByRole('banner')).getByRole('link', { name: 'Save and come back later' });
    expect(later).toHaveAttribute('href', '/register?saved=1');
    expect(screen.getAllByRole('link', { name: 'Save and come back later' })).toHaveLength(1);
  });

  it('says nothing goes live until the shift lead approves it', async () => {
    await open();
    expect(screen.getByText('Drafts save as you go. Nothing is live until your shift lead approves it.')).toBeInTheDocument();
  });

  it('shows the checklist with all five sections not started, and none current', async () => {
    await open('REG-SAMPLE-1');
    const nav = screen.getByRole('navigation', { name: 'Your registration' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((l) => l.textContent)).toEqual([
      'OrganisationNot started',
      'LocationNot started',
      'ServiceNot started',
      'Capacity reportingNot started',
      'ReviewNot started',
    ]);
    expect(links.some((l) => l.hasAttribute('aria-current'))).toBe(false);
    expect(links[0]).toHaveAttribute('href', '/register/REG-SAMPLE-1/organisation');
  });

  it('has no axe violations', async () => {
    const { container } = await open();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
