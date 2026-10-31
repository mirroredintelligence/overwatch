import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DIRECTORY_BODY, directoryEntry } from '@/test/fixtures/network';
import { parseDirectory } from '@/lib/network/parse';
import { NetworkServiceCard } from './NetworkServiceCard';

// TEN-071 (docs/design/network-ui.md, NetworkServices): one service of the network directory. Its name is
// the one link, to the detail; it says whose service it is, what it is, where, when it is open and how to
// phone it, and it has no action but those.

const [first, second] = parseDirectory(DIRECTORY_BODY, 'backend').entries;

function card(entry = first!, over: { own?: boolean } = {}) {
  return render(
    <ul>
      <NetworkServiceCard entry={entry} own={over.own ?? false} orgRef="org-1" />
    </ul>,
  );
}

describe('NetworkServiceCard', () => {
  it('shows the name as the one link, to the detail by the row reference, with the organisation, category and district', () => {
    const { container } = card();
    const link = screen.getByRole('link', { name: 'UCR West' });
    expect(link).toHaveAttribute('href', '/network/services/lst-0001');
    const row = container.querySelector('[data-el="NET-SERVICES-ROW"]')!;
    expect(row).toHaveAttribute('data-service-ref', 'lst-0001');
    expect(row).toHaveAttribute('data-org-ref', 'org-1');
    expect(screen.getByText('Sample Area A')).toBeInTheDocument();
    expect(screen.getByText('Urgent community response · DT4')).toBeInTheDocument();
  });

  it('shows the opening hours and the service line number', () => {
    card();
    expect(screen.getByText('Mon to Fri 08:00 to 20:00')).toBeInTheDocument();
    expect(screen.getByText('Service line 01632 960010')).toBeInTheDocument();
  });

  it('says "No number shared" when there is none, and leaves the district out when there is no place', () => {
    card(second!);
    expect(screen.getByText('No number shared')).toBeInTheDocument();
    expect(screen.getByText('Virtual beds')).toBeInTheDocument();
    expect(screen.getByText('Every day, all day')).toBeInTheDocument();
  });

  it('marks the viewer’s own organisation in words', () => {
    card(first!, { own: true });
    expect(screen.getByText('Your organisation')).toBeInTheDocument();
  });

  it('says a paused listing is not available on the network', () => {
    card(parseDirectory({ ...DIRECTORY_BODY, entries: [directoryEntry({ presentation: 'unavailable' })] }, 'backend').entries[0]);
    expect(screen.getByText('Not available on the network. Phone to confirm.')).toBeInTheDocument();
  });

  it('has nothing shaped like a tenant, grant or source id, and no axe violations', async () => {
    const { container } = card();
    expect(container.innerHTML).not.toMatch(/trust-|tenant|grant|source_/i);
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
