import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { VIEW_SHARING } from '@/test/fixtures/networkAdmin';
import { SCOPES } from '@/lib/networkAdmin/views';
import { AllowlistFields } from './AllowlistFields';

// The fields that leave an organisation for a network, in plain words (TEN-081, design N2: SharingFields).
// The list is rendered from the allowlist the back end returns, not typed here: a field the back end sends
// with no sentence for it cannot be described, so nothing is listed and the page says so.

const SCOPES_FIELDS = VIEW_SHARING.allowlist.scopes;

describe('AllowlistFields', () => {
  it.each(SCOPES)('lists the %s fields in words, one item for each sentence, in a list that names the kind', (scope) => {
    render(<AllowlistFields scope={scope} fields={SCOPES_FIELDS[scope]} />);
    const list = byEl('SHARE-FIELDS-LIST');
    expect(list.tagName).toBe('UL');
    expect(list).toHaveAccessibleName(new RegExp(`Fields shared: ${scope}`, 'i'));
    expect(within(list).getAllByRole('listitem').length).toBeGreaterThan(2);
  });

  it('says the capacity fields as the design does', () => {
    render(<AllowlistFields scope="capacity" fields={SCOPES_FIELDS.capacity} />);
    expect(within(byEl('SHARE-FIELDS-LIST')).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'What the figure counts and its unit',
      'Established capacity',
      'Whether the service can go over established capacity',
      'Level at which the service shows as Limited',
      'How often the service reports',
      'Whether the service is suspended',
      'The latest reported figure and when it was reported',
      'How many bookings were confirmed since that report (a count, never the bookings)',
      'How long a reply is expected, and when the figure counts as old',
    ]);
  });

  it('never lists an internal reference, and never prints a field’s own name', () => {
    for (const scope of SCOPES) {
      const { unmount } = render(<AllowlistFields scope={scope} fields={SCOPES_FIELDS[scope]} />);
      expect(document.body.textContent).not.toMatch(/source_|report_id|valid_until|_id\b|[a-z]+_[a-z]+/);
      unmount();
    }
  });

  it('lists nothing and says it cannot, in an alert, when the back end sends a field there is no sentence for', () => {
    render(<AllowlistFields scope="capacity" fields={[...SCOPES_FIELDS.capacity, 'reporter_name']} />);
    expect(screen.getByRole('alert')).toHaveTextContent('We could not list the fields that are shared. Do not approve this until it is fixed.');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('reporter_name');
  });

  it('lists only the sentences whose fields are sent', () => {
    render(<AllowlistFields scope="criteria" fields={['age_min', 'age_max']} />);
    expect(within(byEl('SHARE-FIELDS-LIST')).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Age range']);
  });

  it('has no accessibility violation', async () => {
    render(
      <main>
        <AllowlistFields scope="directory" fields={SCOPES_FIELDS.directory} />
      </main>,
    );
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
