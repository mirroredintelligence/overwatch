import { describe, expect, it } from 'vitest';
import { OFFER_SAMPLE, SHIFT_SAMPLE, VISIT_SAMPLE } from '@/test/msw/handlers/practitioner';
import { parseAnswer, parseSettings, parseShift, parseVisit } from './answers';

describe('parseShift', () => {
  it('keeps the fields a screen reads and no others', () => {
    expect(parseShift({ ...SHIFT_SAMPLE, internal: 'x', offers: [{ ...SHIFT_SAMPLE.offers[0], bookingId: 'bk-1' }] })).toEqual(SHIFT_SAMPLE);
  });

  it.each([
    ['not an object', 'x'],
    ['an unknown status', { ...SHIFT_SAMPLE, status: 'asleep' }],
    ['an unknown location', { ...SHIFT_SAMPLE, location: 'always' }],
    ['a negative count', { ...SHIFT_SAMPLE, visitsToday: -1 }],
    ['a count that is not whole', { ...SHIFT_SAMPLE, visitsToday: 1.5 }],
    ['offers that are not a list', { ...SHIFT_SAMPLE, offers: 'none' }],
    ['an offer with no sector', { ...SHIFT_SAMPLE, offers: [{ ...SHIFT_SAMPLE.offers[0], sector: undefined }] }],
    ['an offer with an id that is not one', { ...SHIFT_SAMPLE, offers: [{ ...SHIFT_SAMPLE.offers[0], id: '../x' }] }],
    ['an offer time that is not a time', { ...SHIFT_SAMPLE, offers: [{ ...SHIFT_SAMPLE.offers[0], expiresAt: 'soon' }] }],
    ['a next visit with no sector', { ...SHIFT_SAMPLE, next: { ...SHIFT_SAMPLE.next, sector: 5 } }],
    ['a round item in an unknown state', { ...SHIFT_SAMPLE, round: [{ ...SHIFT_SAMPLE.round[0], state: 'lost' }] }],
    ['no round', { ...SHIFT_SAMPLE, round: undefined }],
  ])('refuses %s', (_name, body) => {
    expect(parseShift(body)).toBeNull();
  });

  it('allows no status, no next visit and nothing waiting', () => {
    expect(parseShift({ ...SHIFT_SAMPLE, status: null, next: null, offers: [], round: [], visitsToday: 0 })).toMatchObject({ status: null, next: null, offers: [], round: [] });
  });
});

describe('parseVisit', () => {
  it('keeps an offer without any address or contact, even if sent', () => {
    const parsed = parseVisit({ ...OFFER_SAMPLE, address: '1 Synthetic Street', contact: 'Daughter' });
    expect(parsed).toEqual(OFFER_SAMPLE);
    expect(parsed).not.toHaveProperty('address');
  });

  it.each(['accepted', 'on-my-way', 'arrived'])('keeps the address and contact of a visit that is %s', (state) => {
    expect(parseVisit({ ...VISIT_SAMPLE, state })).toMatchObject({ address: '1 Synthetic Street', contact: 'Daughter, 07000 000000' });
  });

  it.each(['done', 'not-reached', 'declined', 'expired', 'withdrawn'])('drops the address and contact of a visit that is %s', (state) => {
    expect(parseVisit({ ...VISIT_SAMPLE, state })).not.toHaveProperty('address');
  });

  it('drops both when only one is text', () => {
    expect(parseVisit({ ...VISIT_SAMPLE, contact: 5 })).not.toHaveProperty('address');
    expect(parseVisit({ ...VISIT_SAMPLE, address: '' })).not.toHaveProperty('contact');
  });

  it.each([
    ['a reference that is not four digits', { ...OFFER_SAMPLE, reference: 'AB12' }],
    ['an unknown state', { ...OFFER_SAMPLE, state: 'maybe' }],
    ['no need', { ...OFFER_SAMPLE, need: '' }],
    ['a fit that is not minutes', { ...OFFER_SAMPLE, fitsMinutes: 'six' }],
    ['an estimate that is not a time', { ...OFFER_SAMPLE, etaAt: 'later' }],
    ['an unknown location', { ...OFFER_SAMPLE, location: 'gps' }],
    ['a time that is not a time', { ...OFFER_SAMPLE, expiresAt: 'noon' }],
  ])('refuses %s', (_name, body) => {
    expect(parseVisit(body)).toBeNull();
  });
});

describe('parseAnswer and parseSettings', () => {
  it('keep the id and the state, the status and the location', () => {
    expect(parseAnswer({ id: 'v-1', state: 'accepted', more: 1 })).toEqual({ id: 'v-1', state: 'accepted' });
    expect(parseSettings({ status: null, location: 'travel', more: 1 })).toEqual({ status: null, location: 'travel' });
  });

  it('refuse anything else', () => {
    expect(parseAnswer({ id: 'v-1', state: 'lost' })).toBeNull();
    expect(parseAnswer({ id: '', state: 'done' })).toBeNull();
    expect(parseSettings({ location: 'travel' })).toBeNull();
    expect(parseSettings({ status: 'asleep', location: 'travel' })).toBeNull();
  });
});
