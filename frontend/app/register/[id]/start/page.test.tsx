import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import StartPage from './page';

// Register a service: the start page (W23). It lists what to have ready and links on to step 1.

async function open(id = 'REG-SAMPLE-1') {
  return render(await StartPage({ params: Promise.resolve({ id }) }));
}

describe('registration start page', () => {
  it('shows the heading, the time it takes and the five things to have ready', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Register a service' })).toBeInTheDocument();
    expect(screen.getByText('It takes about 10 minutes. Have these ready:')).toBeInTheDocument();
    const list = screen.getByRole('list');
    const items = within(list).getAllByRole('listitem').map((item) => item.textContent);
    expect(items).toEqual([
      'Organisation name and ODS code',
      'The address of the site, or the area you cover',
      'A phone number the coordination team can call',
      'Who owns your criteria, and when they are next reviewed',
      'A mobile number or email for capacity updates',
    ]);
  });

  it('links Start to the organisation step of this registration', async () => {
    await open('REG-SAMPLE-1');
    expect(screen.getByRole('link', { name: 'Start' })).toHaveAttribute('href', '/register/REG-SAMPLE-1/organisation');
    expect(screen.getByRole('link', { name: 'Start' })).toHaveAttribute('data-el', 'REG-START-BTN');
  });

  it('offers Save and come back later, which returns to sign-in with the note, and says nothing goes live', async () => {
    await open();
    const later = screen.getByRole('link', { name: 'Save and come back later' });
    expect(later).toHaveAttribute('href', '/register?saved=1');
    expect(later).toHaveAttribute('data-el', 'REG-START-LATER-BTN');
    expect(screen.getByText('Drafts are saved as you go. Nothing is live until the shift lead approves it.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = await open();
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
