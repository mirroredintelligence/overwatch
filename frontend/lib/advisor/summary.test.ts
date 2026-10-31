import { describe, expect, it } from 'vitest';
import { SUMMARY_NO_DESTINATION, SUMMARY_WITH_DESTINATION } from '@/test/fixtures/backend-shapes';
import { NO_DESTINATION, NOT_BOOKED, NOT_RECORDED, summaryFromParameters, summaryText } from './summary';

// The summary as the back end builds it (H-322, BuildCaseSummary): one row per field in order, a row
// with nothing to say left out. The shapes are the back end's own (`summary_to_fhir`).

describe('summaryFromParameters (W15, H-322)', () => {
  it('reads every row, with the destination, the booking and the data age of the service named', () => {
    expect(summaryFromParameters(SUMMARY_WITH_DESTINATION, true)).toEqual({
      reference: '4821',
      referrer: 'Ambulance crew',
      ageBand: '80+',
      postcode: 'DT4',
      needs: 'Fall with no injury, frailty',
      urgency: 'Within 2 hrs',
      scores: 'NEWS2 2 · Frailty scale 6',
      destination: 'UCR West',
      booked: 'Confirmed 14:03',
      dataAge: '9 min ago',
    });
  });

  it('with no destination chosen says so for the destination, the booking and the data age: it does not leave them blank', () => {
    const summary = summaryFromParameters(SUMMARY_NO_DESTINATION, false);

    expect(summary?.destination).toBe(NO_DESTINATION);
    expect(summary?.booked).toBe(NO_DESTINATION);
    expect(summary?.dataAge).toBe(NO_DESTINATION);
  });

  it('a row the back end left out is not recorded, and no scores read "None given"', () => {
    const summary = summaryFromParameters(SUMMARY_NO_DESTINATION, false);

    expect(summary?.needs).toBe(NOT_RECORDED);
    expect(summary?.urgency).toBe(NOT_RECORDED);
    expect(summary?.scores).toBe('None given');
  });

  it('a destination with no holding booking says it is not booked', () => {
    const rows = (SUMMARY_WITH_DESTINATION.parameter as { name: string; part?: { valueString: string }[] }[]).filter(
      (item) => !(item.name === 'row' && item.part?.[0]?.valueString === 'Booked'),
    );

    expect(summaryFromParameters({ ...SUMMARY_WITH_DESTINATION, parameter: rows }, true)?.booked).toBe(NOT_BOOKED);
  });

  it('is null for anything that is not Parameters, so the route can say it could not be read', () => {
    expect(summaryFromParameters({ resourceType: 'Bundle' }, false)).toBeNull();
    expect(summaryFromParameters(null, false)).toBeNull();
    expect(summaryFromParameters({ resourceType: 'Parameters', parameter: [] }, false)).toBeNull();
  });

  it('reads only the rows it knows, as text: another row or a value that is not text is dropped', () => {
    const summary = summaryFromParameters(
      {
        resourceType: 'Parameters',
        parameter: [
          { name: 'reference', valueString: '4821' },
          { name: 'row', part: [{ name: 'label', valueString: 'Tenant' }, { name: 'value', valueString: 'trust-b' }] },
          { name: 'row', part: [{ name: 'label', valueString: 'Postcode' }, { name: 'value', valueInteger: 7 }] },
        ],
      },
      false,
    );

    expect(JSON.stringify(summary)).not.toContain('trust-b');
    expect(summary?.postcode).toBe(NOT_RECORDED);
  });
});

describe('summaryText (W15)', () => {
  it('is one row per line, "Label: value", in the order of the summary', () => {
    const text = summaryText(summaryFromParameters(SUMMARY_WITH_DESTINATION, true)!);
    const lines = text.split('\n');

    expect(lines[0]).toBe('Referrer: Ambulance crew');
    expect(lines[1]).toBe('Age band: 80+');
    expect(lines).toHaveLength(9);
    expect(text).toContain('Postcode: DT4');
    expect(text).toContain('Destination: UCR West');
    expect(text).toContain('Booked: Confirmed 14:03');
    expect(text).toContain('Data age: 9 min ago');
  });
});

describe('the case number on the summary (DEC-631)', () => {
  it('is the four-digit number the back end holds, never the id used in the address', () => {
    expect(summaryFromParameters(SUMMARY_WITH_DESTINATION, true)?.reference).toBe('4821');
  });
});
