// @vitest-environment node
// Documentation-consistency test for docs/design/network-ui.md (TEN-063, DEC-129, DEC-133 item 4).
// It reads the specification and checks its structure, its element ids, its wording and its rules.
// It builds nothing: no component, route or style is tested here.

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const DOC = resolve(__dirname, '../../../docs/design/network-ui.md');
const TOKENS = resolve(__dirname, '../../app/tokens.css');

function readDoc(): string {
  return existsSync(DOC) ? readFileSync(DOC, 'utf8') : '';
}

function section10(doc: string): string {
  const start = doc.indexOf('## 10. Element ids');
  const end = doc.indexOf('## 11. Telemetry');
  return start >= 0 && end > start ? doc.slice(start, end) : '';
}

// The element-id pattern of the telemetry schema (O05).
const ID_PATTERN = /^[A-Z0-9]+(-[A-Z0-9]+)*$/;
const ID_SHAPE = /^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/;
const MAX_ID_LENGTH = 48;
const MIN_SEGMENTS = 2;
const MAX_SEGMENTS = 5;
const FORBIDDEN_IN_ID = /[<>{}[\]$:*\s]/;
const FORBIDDEN_SEGMENTS = new Set(['ID', 'REF', 'INDEX', 'N']);

// Problems with one candidate id; an empty list means the id is well formed and static.
function idProblems(id: string): string[] {
  const problems: string[] = [];
  if (!ID_PATTERN.test(id)) problems.push('does not match the O05 pattern');
  if (id.length > MAX_ID_LENGTH) problems.push('is longer than 48 characters');
  const segments = id.split('-');
  if (segments.length < MIN_SEGMENTS || segments.length > MAX_SEGMENTS) {
    problems.push('does not have 2 to 5 segments');
  }
  if (FORBIDDEN_IN_ID.test(id)) problems.push('contains a placeholder or a space');
  for (const segment of segments) {
    if (FORBIDDEN_SEGMENTS.has(segment)) problems.push(`has a placeholder segment ${segment}`);
    if (/^[0-9A-F]{8,}$/.test(segment)) problems.push('has a hex run of eight or more digits');
    if (/^[0-9]{3,}$/.test(segment)) problems.push('has a decimal run of three or more digits');
  }
  return problems;
}

// Rows of the markdown tables in a block of text, as arrays of trimmed cells. Each table is a run
// of consecutive lines that start with a pipe; the header and separator rows are kept.
function tables(block: string): string[][][] {
  const found: string[][][] = [];
  let current: string[][] = [];
  for (const line of block.split('\n')) {
    if (line.trim().startsWith('|')) {
      current.push(line.trim().slice(1, -1).split('|').map((cell) => cell.trim()));
    } else if (current.length > 0) {
      found.push(current);
      current = [];
    }
  }
  if (current.length > 0) found.push(current);
  return found;
}

function backticked(text: string): string[] {
  return [...text.matchAll(/`([^`]+)`/g)].map((match) => match[1]);
}

const HEADINGS = [
  '## 1. Rules that bind every screen',
  '## 2. Vocabulary and fixed wording',
  '## 3. Scope header and organisation label',
  '## 4. N3: Network capacity board and directory',
  '## 5. N5: Unavailable and degraded states',
  '## 6. N4: Wall screens',
  '## 7. N1: Network administration',
  '## 8. N2: Sharing with the network',
  '## 9. Variants of existing screens',
  '## 10. Element ids',
  '## 11. Telemetry',
  '## 12. Accessibility and motion',
  '## 13. Build hand-offs and decisions',
  '## 14. Canvas differences',
];

// Wording the sections fix. `{Name}`, `{n}` and the like are placeholders, never constants.
const EXACT_STRINGS = [
  // section 2 table
  'Showing: Our organisation',
  'Showing: Network, {Network name}',
  'Your organisation',
  'Our organisation',
  '{Network name} capacity',
  'Read only',
  'You cannot book or change these services from here. Phone the service to check.',
  '{n} services from {m} organisations',
  '1 service from 1 organisation',
  'Shared by {Organisation name}',
  'No patient information on this screen',
  'Figures are reported by each organisation. Sorted by category, then organisation. Not ranked.',
  'Phone to confirm',
  'Updated {age} ago',
  'Not updated for {duration} · was due {time}',
  'Not available on the network. Phone to confirm.',
  'Service line',
  'No number shared',
  'Entered by the organisation',
  'From the Directory of Services',
  'No services are shared yet',
  'When organisations share their capacity with {Network name}, their services appear here.',
  'No services match this filter',
  'Clear the filter to see all organisations.',
  'All organisations',
  // section 5
  'Network view not available',
  'Ask your administrator.',
  'Back to our organisation',
  'The network view is paused',
  '{Network name} is not sharing capacity at the moment. Phone services to check.',
  'Your organisation has left {Network name}',
  'You can see the history of what was shared until {date}.',
  'See history',
  'No longer shown: {Organisation name}. It stopped sharing on {date}.',
  'Updates from {Organisation name} are delayed. Its services show Not updated.',
  'Network board offline since {time}',
  'Figures are the last known and may be wrong. Use the whiteboard and phone process.',
  'No longer showing {Network name}. Showing: Our organisation.',
  // section 6
  'Wall screens',
  'Online, updated {time}',
  'Offline since {time}',
  'Waiting to be connected',
  'Change board',
  'Unpair',
  'Re-pair',
  'Add a wall screen',
  'Which board does {Screen name} show?',
  'Your organisation is not in a network.',
  'The screen changes the next time it refreshes. Its header always says which board it shows.',
  'Check before you connect',
  "You are connecting a screen to {Organisation name}. It will show our organisation's capacity only. It never shows patient information.",
  'First seen {time} · {device class}',
  'Unpair {Screen name}?',
  'The screen stops showing the board and returns to its pairing code. You can pair it again at any time.',
  'Unpair screen',
  'This screen is not connected.',
  'Ask your lead to connect it.',
  'Code shown on the screen',
  'Screen connected',
  // section 7
  "You see who has joined, what each organisation agreed to share and whether it is arriving. You never see another organisation's private data.",
  'Agreement version {n} is available',
  'Add an organisation',
  'End membership for {Organisation name}?',
  "Its sharing stops now. What it already shared stays in the history, marked with today's date.",
  'A second administrator must confirm this.',
  'Only the reference and version are stored, never the agreement itself.',
  'Record agreement',
  'Waiting for the organisation',
  'Waiting for the network owner',
  'Nothing here yet.',
  'Outside the area',
  'Outside the pilot',
  'Duplicate listing',
  'Data quality',
  'Safety concern',
  'Last update received {time}',
  'Delay {duration}',
  'Updates refused {n}',
  'The code is on the organisation',
  'We could not add that organisation. Check the code with them.',
  // section 8
  'Sharing with the network',
  'Sharing is read only. Other organisations see only the fields listed here. No patient information is ever shared.',
  'Sharing since {date}',
  'Waiting for your approval',
  'Not sharing',
  'Ended on {date}',
  'End sharing {scope}?',
  "New data stops being shared straight away. What was already shared stays in the network history, marked with today's date.",
  'Leave {Network name}?',
  'All your sharing ends now. What was already shared stays in the history, marked with the date you left.',
  'Leave network',
  'Agreement version {n} is available.',
  'Accept version {n}',
  "Never shared: reporters' names, phone numbers, devices and PINs; links and codes; messages sent or received; bookings and cases; audit entries; anything about a patient.",
];

// The three sentences that hold the read-only, identifier and header rules (test 9).
const RULE_SENTENCES = [
  'Network rows have no Request booking, I phoned, They declined, clinical escalation or alert subscription.',
  'The browser holds and sends no tenant, network or scope identifier.',
  'The scope header never disappears, including in the Last known and unavailable states.',
];

// The DTO fields of the allowlist, as TEN-052 names them (section 8 of the prompt).
const ALLOWLIST: Record<string, string[]> = {
  Directory: [
    'service_name', 'category', 'active', 'source', 'contact_label', 'contact_phone',
    'location_name', 'city', 'postal_district', 'latitude', 'longitude', 'opening_hours',
    'source_service_id', 'source_version',
  ],
  Capacity: [
    'measure', 'unit_label', 'established_capacity', 'can_exceed_established',
    'limited_level_percent', 'cadence', 'suspended', 'value', 'reported_at', 'confirmed_since',
    'reply_window_minutes', 'stale_warning_hours', 'source_service_id', 'source_version',
    'report_id', 'valid_until',
  ],
  Criteria: [
    'age_min', 'age_max', 'districts', 'accepts', 'excludes', 'review_by', 'version',
    'source_criteria_id', 'source_service_id',
  ],
};

// Element ids the spec must catalogue (section 10 of the prompt). Every one must appear on a
// control line in the artboards.
const NEW_IDS = [
  'SCOPE-HEADER-LABEL', 'SCOPE-SWITCH-OWN-LINK', 'SCOPE-SWITCH-NETWORK-LINK', 'SCOPE-READONLY-NOTE',
  'SCOPE-BANNER-NOTICE', 'NET-BOARD-TILE', 'NET-BOARD-ROW', 'NET-BOARD-ORG-ALL-CHIP',
  'NET-BOARD-ORG-CHIP', 'NET-BOARD-VIEW-GRID-BTN', 'NET-BOARD-VIEW-LIST-BTN', 'NET-BOARD-PHONE-LINK',
  'NET-BOARD-HISTORY-LINK', 'NET-SERVICES-ROW', 'NET-SERVICES-ORG-CHIP', 'NET-SERVICES-CATEGORY-CHIP',
  'NET-SERVICE-CRITERIA-SECTION', 'NET-STATE-PANEL', 'NET-STATE-BACK-LINK', 'NET-STATE-RETRY-BTN',
  'NADM-MEMBERS-TABLE', 'NADM-MEMBER-ADD-BTN', 'NADM-MEMBER-CODE-INPUT', 'NADM-MEMBER-SEND-BTN',
  'NADM-MEMBER-END-BTN', 'NADM-MEMBER-END-CONFIRM-BTN', 'NADM-AGREEMENT-REFERENCE-INPUT',
  'NADM-AGREEMENT-VERSION-INPUT', 'NADM-AGREEMENT-RECORD-BTN', 'NADM-GRANTS-TABLE',
  'NADM-GRANT-APPROVE-BTN', 'NADM-GRANT-DECLINE-BTN', 'NADM-LISTINGS-TABLE', 'NADM-LISTING-ADMIT-BTN',
  'NADM-LISTING-DECLINE-BTN', 'NADM-LISTING-PAUSE-BTN', 'NADM-LISTING-REINSTATE-BTN',
  'NADM-LISTING-REASON-SELECT', 'NADM-HEALTH-TABLE', 'NADM-GRANT-DECLINE-CONFIRM-BTN', 'NADM-LISTING-CONFIRM-BTN',
  'NADM-HISTORY-LINK', 'SHARE-SCOPE-CARD',
  'SHARE-FIELDS-LIST', 'SHARE-APPROVE-BTN', 'SHARE-DECLINE-BTN', 'SHARE-DECLINE-CONFIRM-BTN', 'SHARE-PROPOSE-BTN', 'SHARE-END-BTN',
  'SHARE-END-CONFIRM-BTN', 'SHARE-LEAVE-BTN', 'SHARE-LEAVE-CONFIRM-BTN', 'SHARE-AGREEMENT-ACCEPT-BTN',
  'SHARE-HISTORY-LINK', 'SCREENS-LIST-TABLE', 'SCREENS-ADD-BTN', 'SCREENS-BOARD-BTN',
  'SCREENS-BOARD-OWN-RADIO', 'SCREENS-BOARD-NETWORK-RADIO', 'SCREENS-BOARD-SAVE-BTN',
  'SCREENS-BOARD-CANCEL-BTN', 'SCREENS-UNPAIR-BTN', 'SCREENS-UNPAIR-CONFIRM-BTN', 'SCREENS-REPAIR-BTN',
  'SCREENS-CLAIM-CONFIRM-BTN', 'SCREENS-CLAIM-CANCEL-BTN',
];

// Existing ids that keep their meaning in the network variants, each found in docs/plan/prompts or
// docs/spec (W05, the amended W-prompts and contracts.md). No id is invented here.
const REUSED_IDS = ['WALL-TILE', 'ADV-CRIT-DIALOG', 'ADV-MAP-TOGGLE-LIST', 'ADV-MAP-TOGGLE-MAP', 'EXEC-ALERT'];

// Lines that are controls or named elements in an artboard. Each must end with `(el: <ID>)`.
// The first six are the prompt's control kinds; the rest are the element kinds the artboards use
// for banners, labels, tiles, rows, panels, tables, cards and lists, which need ids too.
const ELEMENT_LINE = /^\[(btn|input|chip|link|radio|select|label|banner|tile|row|section|panel|table|card|list)\b/;
const EL_SUFFIX = /\(el: ([A-Z0-9-]+)\)\s*$/;

describe('network-ui.md: structure', () => {
  it('the document exists and is readable text', () => {
    expect(existsSync(DOC)).toBe(true);
    expect(readDoc().length).toBeGreaterThan(0);
  });

  it('has the fourteen section headings in order, and a ### heading for each of N1 to N5', () => {
    const doc = readDoc();
    const lines = doc.split('\n');
    const positions = HEADINGS.map((heading) => lines.indexOf(heading));
    for (const [index, position] of positions.entries()) {
      expect(position, `missing heading: ${HEADINGS[index]}`).toBeGreaterThanOrEqual(0);
    }
    for (let index = 1; index < positions.length; index += 1) {
      expect(positions[index], `heading out of order: ${HEADINGS[index]}`).toBeGreaterThan(
        positions[index - 1],
      );
    }
    for (const n of ['N1:', 'N2:', 'N3:', 'N4:', 'N5:']) {
      const found = lines.some((line) => line.startsWith(`### ${n}`));
      expect(found, `no ### heading starting ${n}`).toBe(true);
    }
  });
});

describe('network-ui.md: element ids', () => {
  it('parses into a new table and a reused table, and every id is well formed and unique', () => {
    const blocks = tables(section10(readDoc()));
    expect(blocks.length, 'section 10 needs a new-ids table and a reused-ids table').toBe(2);
    const [newTable, reusedTable] = blocks;
    const newIds = newTable.slice(2).flatMap((row) => backticked(row[0]));
    const reusedIds = reusedTable.slice(2).flatMap((row) => backticked(row[0]));
    expect(newIds.length).toBeGreaterThan(0);
    expect(reusedIds.length).toBeGreaterThan(0);
    const all = [...newIds, ...reusedIds];
    expect(new Set(all).size, 'an id is repeated').toBe(all.length);
    for (const id of all) {
      expect(idProblems(id), `id ${id}`).toEqual([]);
    }
  });

  it('catalogues every id the prompt names, and only those', () => {
    const blocks = tables(section10(readDoc()));
    const newIds = blocks[0]?.slice(2).flatMap((row) => backticked(row[0])) ?? [];
    expect([...newIds].sort()).toEqual([...NEW_IDS].sort());
    const reusedIds = blocks[1]?.slice(2).flatMap((row) => backticked(row[0])) ?? [];
    expect([...reusedIds].sort()).toEqual([...REUSED_IDS].sort());
  });

  it('no id embeds a dynamic value and only the three data-*-ref attributes carry identity', () => {
    const doc = readDoc();
    const blocks = tables(section10(doc));
    for (const id of [...NEW_IDS, ...REUSED_IDS]) {
      expect(FORBIDDEN_IN_ID.test(id), `placeholder in ${id}`).toBe(false);
    }
    const carriers = new Set(
      [...doc.matchAll(/data-[a-z]+(?:-[a-z]+)*/g)]
        .map((match) => match[0])
        .filter((attribute) => /-(ref|id)$/.test(attribute)),
    );
    expect([...carriers].sort()).toEqual(['data-org-ref', 'data-row-ref', 'data-service-ref']);
    expect(blocks.length).toBe(2);
  });

  it('every control line ends with an id, every new id is used on a control line, and every id named in backticks is catalogued', () => {
    const doc = readDoc();
    const blocks = tables(section10(doc));
    const catalogue = new Set([
      ...(blocks[0]?.slice(2).flatMap((row) => backticked(row[0])) ?? []),
      ...(blocks[1]?.slice(2).flatMap((row) => backticked(row[0])) ?? []),
    ]);
    const used = new Set<string>();
    for (const raw of doc.split('\n')) {
      const line = raw.trim();
      if (!ELEMENT_LINE.test(line)) continue;
      const suffix = EL_SUFFIX.exec(line);
      expect(suffix, `element line without an id: ${line}`).not.toBeNull();
      const id = suffix?.[1] ?? '';
      expect(catalogue.has(id), `element line uses an id not in section 10: ${id}`).toBe(true);
      used.add(id);
    }
    for (const id of NEW_IDS) {
      expect(used.has(id), `new id not used on any control line: ${id}`).toBe(true);
    }
    for (const token of [...doc.matchAll(/`([^`\s]+)`/g)].map((match) => match[1])) {
      if (ID_SHAPE.test(token)) {
        expect(catalogue.has(token), `backticked id not catalogued: ${token}`).toBe(true);
      }
    }
  });

  it('the id checks report the three bad catalogues, so the test cannot pass by being empty', () => {
    expect(idProblems('NET-BOARD-TILE-{ID}').length).toBeGreaterThan(0);
    expect(idProblems('net-board-tile').length).toBeGreaterThan(0);
    expect(idProblems('NET-1234567-ROW').length).toBeGreaterThan(0);
  });
});

describe('network-ui.md: wording, rules and tokens', () => {
  it('contains every exact string of section 2, section 5 and sections 6 to 8', () => {
    const doc = readDoc();
    for (const text of EXACT_STRINGS) {
      expect(doc.includes(text), `missing exact wording: ${text}`).toBe(true);
    }
  });

  it('keeps the voice and the neutrality: no place, organisation, phone number, exclamation, emoji, postcode, NHS number, superlative or unranked order', () => {
    const doc = readDoc();
    expect(doc.length).toBeGreaterThan(0);
    const prose = doc.replace(/`[^`]*`/g, ' ');
    expect(doc).not.toMatch(/Dorset/);
    expect(doc).not.toMatch(/Trust/);
    expect(prose.match(/\d{7,}/g) ?? [], 'a run of seven or more digits').toEqual([]);
    expect(prose.includes('!'), 'an exclamation mark').toBe(false);
    expect(doc).not.toMatch(/\p{Extended_Pictographic}/u);
    expect(doc.match(/\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b/gi) ?? [], 'a postcode').toEqual([]);
    expect(doc.match(/(?<![0-9])(?:[0-9]{10}|[0-9]{3}[ -][0-9]{3}[ -][0-9]{4})(?![0-9])/g) ?? [], 'an NHS number').toEqual([]);
    expect(doc).not.toMatch(/\b(best|recommended)\b/i);
    for (const match of doc.matchAll(/ranked/gi)) {
      const start = match.index ?? 0;
      expect(doc.slice(Math.max(0, start - 4), start), 'ranked without Not').toBe('Not ');
    }
  });

  it('adds no colour, no status word, no Banner tone and no token; every token named is declared in tokens.css', () => {
    const doc = readDoc();
    expect(doc).not.toMatch(/#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/);
    expect(doc).toContain('No tone, status word or token is added.');
    const declared = new Set(
      [...readFileSync(TOKENS, 'utf8').matchAll(/(?<![\w-])(--[\w-]+)\s*:/g)].map((match) => match[1]),
    );
    const named = [...doc.matchAll(/--(?:c|space|type|dur|radius)[\w-]*/g)].map((match) => match[0]);
    expect(named.length).toBeGreaterThan(0);
    for (const token of named) {
      expect(declared.has(token), `undeclared token ${token}`).toBe(true);
    }
    const allowed = new Set(['info', 'warning', 'offline']);
    for (const match of doc.matchAll(/tones?:?\s+((?:`[a-z]+`(?:,\s*|\s+and\s+|\s+or\s+)?)+)/g)) {
      for (const tone of backticked(match[1])) {
        expect(allowed.has(tone), `not a Banner tone: ${tone}`).toBe(true);
      }
    }
  });

  it('lists every allowlist field once, on a row of a fixed scope, and repeats a field only as an internal reference', () => {
    const doc = readDoc();
    const rows = tables(doc)
      .flat()
      .filter((row) => ['Directory', 'Capacity', 'Criteria'].includes(row[0]) && row.length >= 3);
    const seen = new Map<string, string[]>();
    for (const row of rows) {
      for (const field of backticked(row[1])) {
        const scopes = seen.get(field) ?? [];
        scopes.push(`${row[0]}|${row[2]}`);
        seen.set(field, scopes);
      }
    }
    for (const [scope, fields] of Object.entries(ALLOWLIST)) {
      for (const field of fields) {
        expect(seen.has(field), `allowlist field missing from the table: ${scope} ${field}`).toBe(true);
      }
    }
    for (const [field, entries] of seen) {
      const scopes = new Set(entries.map((entry) => entry.split('|')[0]));
      const internal = entries.every((entry) => entry.endsWith('not listed (internal reference)'));
      if (scopes.size > 1 && !internal) {
        expect.fail(`field under two scopes: ${field}`);
      }
    }
  });

  it('states the read-only, identifier and header rules in the exact sentences, and keeps the forbidden buttons off the network artboards', () => {
    const doc = readDoc();
    for (const sentence of RULE_SENTENCES) {
      expect(doc.includes(sentence), `missing rule sentence: ${sentence}`).toBe(true);
    }
    const networkArtboards = doc.slice(doc.indexOf('## 4. N3:'), doc.indexOf('## 6. N4:'));
    for (const forbidden of ['[btn] Request booking', '[btn] I phoned', '[btn] They declined']) {
      expect(networkArtboards.includes(forbidden), `forbidden control: ${forbidden}`).toBe(false);
    }
  });
});
