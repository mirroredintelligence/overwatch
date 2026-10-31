import { describe, expect, it } from 'vitest';
import { VIEW_SHARING } from '@/test/fixtures/networkAdmin';
import { checkLabels, FIELD_LABELS, labelsFor } from './fieldLabels';
import { SCOPES } from './views';

// The words for what leaves an organisation (TEN-081, design section 8, "Field labels"). The labels are
// keyed by the DTO field names of `domain/rules/projection.py`; the back end's own list of what may travel
// (the sharing read's `allowlist`, written by the back end's converter into the fixture) is what the screen
// lists. This test fails when a field the back end sends has no label, or a label names a field the back
// end does not send, so a field cannot start to travel without a sentence for it, and a sentence cannot
// describe a field that does not.

const ALLOWLIST = VIEW_SHARING.allowlist.scopes;

describe('the labels and the allowlist', () => {
  it.each(SCOPES)('cover every %s field the back end lists, and no other', (scope) => {
    expect(checkLabels(scope, ALLOWLIST[scope])).toEqual({ unlabelled: [], unused: [] });
  });

  it('name a field once: no field is in two labels', () => {
    for (const scope of SCOPES) {
      const all = FIELD_LABELS[scope].flatMap((group) => group.fields);
      expect(new Set(all).size, scope).toBe(all.length);
    }
  });

  it('say a field that has no label as unlabelled, and a label with no field as unused', () => {
    expect(checkLabels('capacity', [...ALLOWLIST.capacity, 'reporter_name'])).toEqual({ unlabelled: ['reporter_name'], unused: [] });
    expect(checkLabels('criteria', ALLOWLIST.criteria.filter((f) => f !== 'review_by'))).toEqual({ unlabelled: [], unused: ['Review-by date'] });
  });

  it('keep the internal references out of what is listed', () => {
    for (const scope of SCOPES) {
      const listed = labelsFor(scope, ALLOWLIST[scope]);
      expect(listed.join(' ')).not.toMatch(/source_|report_id|valid_until|_id\b/);
    }
  });
});

describe('labelsFor', () => {
  it('lists the capacity fields in the design’s words, in the table’s order', () => {
    expect(labelsFor('capacity', ALLOWLIST.capacity)).toEqual([
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

  it('lists the directory fields in the design’s words', () => {
    expect(labelsFor('directory', ALLOWLIST.directory)).toEqual([
      'Service name',
      'Service category',
      'Whether the service is active',
      'Where the entry came from',
      'Service line name and number',
      'Location name and town or city',
      'Postcode district only (for example DT4)',
      'Map position of the location',
      'Opening hours',
    ]);
  });

  it('lists the criteria fields in the design’s words', () => {
    expect(labelsFor('criteria', ALLOWLIST.criteria)).toEqual(['Age range', 'Postcode districts', 'Needs accepted and needs excluded', 'Review-by date', 'Current version number']);
  });

  it('lists only the labels whose fields are sent', () => {
    expect(labelsFor('criteria', ['age_min', 'age_max'])).toEqual(['Age range']);
  });
});
