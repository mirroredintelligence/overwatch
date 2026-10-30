import { describe, expect, it } from 'vitest';
import { addressesFrom, myServicesFrom, reviewRowsFrom, statusFrom, viewFromRecord } from './applicant';

// The applicant's reads, mapped from the back end's answers (W7B A1, routes_registration_views.py) to
// the shapes the screens use. The mapping keeps what a screen shows and nothing else: no contact
// number, no address beyond the label, no tenant. Sample values only.

const RECORD = {
  registrationId: 'REG-SAMPLE-1',
  status: 'draft',
  serviceId: 'SVC-SAMPLE-1',
  serviceName: 'Community nursing',
  submittedAt: null,
  lastModified: '2026-10-30T09:00:00Z',
  invitationExpiresAt: '2026-11-01T18:00:00Z',
  note: '',
  noteFrom: null,
  steps: {
    organisation: {
      state: 'complete',
      values: { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contactEmail: 'sam@example.test', contactPhone: null },
      problems: [],
    },
    location: { state: 'not-started', values: {}, problems: [] },
    service: { state: 'needs-attention', values: { category: 'community-nursing' }, problems: [{ field: 'spoaPhone', message: 'Enter a phone number' }] },
    reporting: { state: 'complete', values: { measure: 'beds', contactMobileEnding: '456', hasContactEmail: false }, problems: [] },
    api: { state: 'not-started', values: {}, problems: [] },
  },
};

describe('viewFromRecord', () => {
  it('keeps the id, status, service name and the saved steps in the screens’ names, and drops the rest', () => {
    const view = viewFromRecord(RECORD);
    expect(view).toEqual({
      id: 'REG-SAMPLE-1',
      status: 'draft',
      serviceName: 'Community nursing',
      steps: {
        organisation: {
          state: 'complete',
          values: { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contactEmail: 'sam@example.test' },
          problems: [],
        },
        location: { state: 'not-started', values: {}, problems: [] },
        service: { state: 'needs-attention', values: { category: 'community-nursing' }, problems: [{ field: 'spoaPhone', message: 'Enter a phone number' }] },
        reporting: { state: 'complete', values: { measure: 'beds', contactMobileEnding: '456', hasContactEmail: false }, problems: [] },
        api: { state: 'not-started', values: {}, problems: [] },
      },
    });
  });

  it('never passes a phone number, a postcode or a tenant through, even if the back end sent one', () => {
    const leaky = {
      ...RECORD,
      tenantId: 'tenant-a',
      steps: {
        ...RECORD.steps,
        organisation: { ...RECORD.steps.organisation, values: { ...RECORD.steps.organisation.values, contactPhone: '07700900456' } },
      },
    };
    const text = JSON.stringify(viewFromRecord(leaky));
    expect(text).not.toContain('07700900456');
    expect(text).not.toContain('tenant-a');
  });

  it('is null for an answer that is not a record, or whose status or steps are not what the screens need', () => {
    expect(viewFromRecord(null)).toBeNull();
    expect(viewFromRecord({ ...RECORD, status: 'pending-ish' })).toBeNull();
    expect(viewFromRecord({ ...RECORD, steps: undefined })).toBeNull();
    expect(viewFromRecord({ ...RECORD, registrationId: 7 })).toBeNull();
  });
});

describe('reviewRowsFrom', () => {
  it('gives one row per step that is answered, complete or needing attention, with the back end’s words', () => {
    const rows = reviewRowsFrom(viewFromRecord(RECORD)!);
    expect(rows).toEqual([
      { key: 'organisation', status: 'complete', summary: '' },
      { key: 'service', status: 'needs-attention', summary: 'Enter a phone number' },
      { key: 'reporting', status: 'complete', summary: '' },
    ]);
  });
});

describe('myServicesFrom', () => {
  it('maps each registration to the state and the detail the screen words, and leaves out none but a draft nobody sent', () => {
    const rows = myServicesFrom({
      registrations: [
        { registrationId: 'R1', serviceId: 'S1', serviceName: 'One', status: 'live', submittedAt: '2026-10-01T09:00:00Z' },
        { registrationId: 'R2', serviceId: 'S2', serviceName: 'Two', status: 'reverify', submittedAt: '2026-10-01T09:00:00Z' },
        { registrationId: 'R3', serviceId: 'S3', serviceName: 'Three', status: 'in-review', submittedAt: '2026-10-02T09:00:00Z' },
        { registrationId: 'R4', serviceId: 'S4', serviceName: 'Four', status: 'needs-changes', submittedAt: '2026-10-02T09:00:00Z' },
        { registrationId: 'R5', serviceId: 'S5', serviceName: 'Five', status: 'not-approved', submittedAt: '2026-10-02T09:00:00Z' },
        { registrationId: 'R6', serviceId: 'S6', serviceName: 'Six', status: 'draft', submittedAt: null },
      ],
    });
    expect(rows?.map((row) => [row.id, row.state])).toEqual([
      ['R1', 'active'],
      ['R2', 'review-due'],
      ['R3', 'pending-approval'],
      ['R4', 'pending-approval'],
      ['R5', 'not-approved'],
    ]);
    expect(rows?.[2]?.detail).toBe('Waiting for the shift lead');
    expect(rows?.[3]?.detail).toBe('The shift lead has sent it back');
    expect(rows?.[0]).toEqual({ id: 'R1', serviceName: 'One', state: 'active', detail: 'Live' });
  });

  it('is null for an answer with no list', () => {
    expect(myServicesFrom({})).toBeNull();
  });
});

describe('statusFrom', () => {
  it('keeps the note as the notes list, the sender as the role, and the details the status page shows', () => {
    const view = statusFrom({
      registrationId: 'REG-SAMPLE-1',
      status: 'needs-changes',
      serviceName: 'Community nursing',
      submittedAt: '2026-10-29T09:00:00Z',
      note: 'Check the phone number.',
      noteFrom: 'lead',
      reason: null,
      firstPromptAt: null,
      reviewRequestedAt: null,
      testSentAt: '2026-10-29T10:00:00Z',
      details: { spoaPhone: '01305 000111', criteriaOwner: null, reportingPhoneEnding: '456' },
    });
    expect(view).toEqual({
      status: 'needs-changes',
      serviceName: 'Community nursing',
      submittedAt: '2026-10-29T09:00:00Z',
      notes: ['Check the phone number.'],
      noteFrom: { role: 'lead' },
      details: { spoaPhone: '01305 000111', reportingPhoneEnding: '456' },
    });
  });

  it('is null for an answer with no status or service name', () => {
    expect(statusFrom({ status: 'live' })).toBeNull();
  });
});

describe('addressesFrom', () => {
  it('keeps each address’s id and label, at most twenty', () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ id: `U${i}`, label: `${i} High Street, Dorchester`, extra: 'x' }));
    const list = addressesFrom({ addresses: many });
    expect(list).toHaveLength(20);
    expect(list?.[0]).toEqual({ id: 'U0', label: '0 High Street, Dorchester' });
  });

  it('is null for an answer with no list', () => {
    expect(addressesFrom({})).toBeNull();
  });
});
