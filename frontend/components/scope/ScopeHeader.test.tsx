import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OrgLabel } from './OrgLabel';
import { ReadOnlyNote } from './ReadOnlyNote';
import { ScopeHeader } from './ScopeHeader';
import { ScopeNotice } from './ScopeNotice';
import { ScopeSwitch } from './ScopeSwitch';

// TEN-069 (docs/design/network-ui.md section 3): the permanent scope header, the switch between the two
// route families, the organisation label with the own-row marker, and the read-only note. The header
// says, in words, whose figures are on the page. It takes no tenant, network or scope identifier: a
// network is named by its display name and the links are fixed routes.

const LINKS = { ownHref: '/advisor/board', networkHref: '/network/board' };

describe('ScopeHeader', () => {
  it('is a landmark named "Which board you are viewing"', () => {
    render(<ScopeHeader scope="own" />);
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toBeInTheDocument();
  });

  it('says "Showing: Our organisation" on the organisation’s own board', () => {
    render(<ScopeHeader scope="own" />);
    const label = screen.getByText('Showing: Our organisation');
    expect(label).toHaveAttribute('data-el', 'SCOPE-HEADER-LABEL');
  });

  it('says "Showing: Network, {name}" on a network board, with the network’s display name', () => {
    render(<ScopeHeader scope="network" networkName="Sample Network" />);
    expect(screen.getByText('Showing: Network, Sample Network')).toHaveAttribute('data-el', 'SCOPE-HEADER-LABEL');
  });

  it('says it in text, never colour alone', () => {
    const { container } = render(<ScopeHeader scope="network" networkName="Sample Network" />);
    expect(container.textContent).toContain('Showing: Network, Sample Network');
  });

  it('prints a name that carries markup as text', () => {
    const { container } = render(<ScopeHeader scope="network" networkName="<b>Net</b>" />);
    expect(container.querySelector('b')).toBeNull();
    expect(screen.getByText('Showing: Network, <b>Net</b>')).toBeInTheDocument();
  });

  it('shows no switch when the viewer has no network to switch to', () => {
    render(<ScopeHeader scope="own" />);
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('shows the switch when it is given the two routes, and marks the current one', () => {
    render(<ScopeHeader scope="own" switchTo={LINKS} />);
    const nav = screen.getByRole('navigation', { name: 'Choose the board' });
    const own = within(nav).getByRole('link', { name: 'Our organisation' });
    const network = within(nav).getByRole('link', { name: 'Network' });
    expect(own).toHaveAttribute('href', '/advisor/board');
    expect(own).toHaveAttribute('aria-current', 'page');
    expect(own).toHaveAttribute('data-el', 'SCOPE-SWITCH-OWN-LINK');
    expect(network).toHaveAttribute('href', '/network/board');
    expect(network).not.toHaveAttribute('aria-current');
    expect(network).toHaveAttribute('data-el', 'SCOPE-SWITCH-NETWORK-LINK');
  });

  it('marks the network link as current on a network board', () => {
    render(<ScopeHeader scope="network" networkName="Sample Network" switchTo={LINKS} />);
    expect(screen.getByRole('link', { name: 'Network' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Our organisation' })).not.toHaveAttribute('aria-current');
  });

  it('is a navigation, never a parameter: the links are plain routes with no identifier in them', () => {
    const { container } = render(<ScopeHeader scope="network" networkName="Sample Network" switchTo={LINKS} />);
    for (const link of container.querySelectorAll('a')) expect(link.getAttribute('href')).not.toMatch(/[?=&]|net-|tenant|scope/i);
  });

  it('has no switch on a wall, even when given the routes', () => {
    render(<ScopeHeader scope="network" networkName="Sample Network" switchTo={LINKS} variant="wall" />);
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByText('Showing: Network, Sample Network')).toBeInTheDocument();
  });

  it('has no axe violations in any form', async () => {
    const { container } = render(
      <main>
        <ScopeHeader scope="own" />
        <ScopeHeader scope="network" networkName="Sample Network" switchTo={LINKS} />
        <ScopeHeader scope="own" variant="wall" />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('ScopeSwitch', () => {
  it('is a nav of two links, in the order own then network', () => {
    render(<ScopeSwitch current="own" {...LINKS} />);
    expect(screen.getAllByRole('link').map((a) => a.textContent)).toEqual(['Our organisation', 'Network']);
  });
});

describe('OrgLabel', () => {
  it('shows the organisation’s name', () => {
    render(<OrgLabel name="Sample Area B" />);
    expect(screen.getByText('Sample Area B')).toBeInTheDocument();
    expect(screen.queryByText('Your organisation')).toBeNull();
  });

  it('marks the viewer’s own organisation with the words "Your organisation"', () => {
    render(<OrgLabel name="Sample Area A" own />);
    expect(screen.getByText('Sample Area A')).toBeInTheDocument();
    expect(screen.getByText('Your organisation')).toBeInTheDocument();
  });

  it('prints a name as text', () => {
    const { container } = render(<OrgLabel name="<i>Area</i>" />);
    expect(container.querySelector('i')).toBeNull();
  });
});

describe('ReadOnlyNote', () => {
  it('says the services cannot be booked or changed from here, and to phone the service', () => {
    render(<ReadOnlyNote />);
    const note = screen.getByRole('status');
    expect(note).toHaveAttribute('data-el', 'SCOPE-READONLY-NOTE');
    expect(note).toHaveTextContent('Read only');
    expect(note).toHaveTextContent('You cannot book or change these services from here. Phone the service to check.');
    expect(note).toHaveAttribute('data-tone', 'info');
  });
});

describe('ScopeNotice', () => {
  it('shows a notice of the tone it is given, with the id of a scope notice', () => {
    render(<ScopeNotice tone="warning" title="Updates from Sample Area B are delayed. Its services show Not updated." />);
    const notice = screen.getByRole('alert');
    expect(notice).toHaveAttribute('data-el', 'SCOPE-BANNER-NOTICE');
    expect(notice).toHaveAttribute('data-tone', 'warning');
  });
});
